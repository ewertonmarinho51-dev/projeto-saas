"""
Serviço ÚNICO de cesta — recalcula o preço do item a partir da seleção
GRAVADA, igual para o Banco de Preços manual e a Pesquisa Automática.

Antes, incluir ou excluir uma referência na revisão mudava só o status
dela: o preço estimado do item continuava o calculado pela máquina, e a
memória de cálculo descrevia uma cesta que já não existia. Agora toda
mudança de seleção passa por aqui, e o número é refeito com o mesmo
`estatistica.estimar` do pipeline — não há segundo cálculo.

As linhas lidas são as de `pesquisa_preco_referencias` (o servidor é a
fonte da verdade, não o `session_state`): reabrir a pesquisa em outra
sessão mostra a mesma cesta e o mesmo preço.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal, InvalidOperation

from . import estatistica
from .estados import EstadoItem
from .modelo import Fonte, NaturezaValor, Referencia
from .perfil import PerfilNormativo

SELECIONADA = "selected"
# `warning` é a referência DA CESTA que o motor sinalizou como discrepante:
# continua dentro até o revisor decidir. Contá-la fora seria excluí-la em
# silêncio no primeiro recálculo — exatamente o que o pacote proíbe.
NA_CESTA = frozenset({SELECIONADA, "warning"})


def _decimal(valor) -> Decimal | None:
    if valor in (None, ""):
        return None
    try:
        return Decimal(str(valor))
    except (InvalidOperation, ValueError, TypeError):
        return None


def _data(valor) -> date | None:
    try:
        return date.fromisoformat(str(valor)[:10]) if valor else None
    except ValueError:
        return None


def referencia_da_linha(linha: dict) -> Referencia:
    """Linha gravada → `Referencia`, com o preço NORMALIZADO gravado."""
    try:
        natureza = NaturezaValor(str(linha.get("natureza_valor") or "outro"))
    except ValueError:
        natureza = NaturezaValor.OUTRO
    return Referencia(
        fonte=Fonte(id=str(linha.get("fonte_id") or ""),
                    nome=str(linha.get("fonte_nome") or ""),
                    tipo=str(linha.get("fonte_tipo") or "outro")),
        id_externo=str(linha.get("id_externo") or ""),
        bruto=dict(linha.get("bruto") or {}),
        descricao_original=str(linha.get("descricao_original") or ""),
        unidade_original=linha.get("unidade_original"),
        valor_unitario_original=_decimal(linha.get("valor_unitario_original")),
        natureza_valor=natureza,
        orgao=linha.get("orgao"),
        data_compra=_data(linha.get("data_compra")),
        unidade_normalizada=linha.get("unidade_normalizada"),
        valor_unitario_normalizado=_decimal(
            linha.get("valor_unitario_normalizado")),
    )


def _compoe_cesta(referencia: Referencia) -> bool:
    """Preço praticado/homologado/contratado/adjudicado, ou cotação direta
    registrada com a trilha do art. 23, § 1º, IV (`cotacao.admissivel`)."""
    from . import cotacao

    return referencia.serve_de_preco or cotacao.admissivel(referencia)


def _na_cesta_com_preco(linha: dict) -> bool:
    return (str(linha.get("status")) in NA_CESTA
            and _decimal(linha.get("valor_unitario_normalizado")) is not None
            and _compoe_cesta(referencia_da_linha(linha)))


def consideradas(linhas: list[dict]) -> list[dict]:
    """
    As linhas que ENTRAM no cálculo — a única definição do "N" de N/3.

    Na cesta (`selected` ou `warning`), com preço normalizado e natureza
    de preço. Relatório, quadro, XLSX, GovBot, tela e o próprio cálculo
    perguntam aqui; ninguém repete `status == "selected"` por conta
    própria (dossiê BP, tema 1: quatro superfícies esqueciam a
    sinalizada, que continua na média).
    """
    return [linha for linha in linhas if _na_cesta_com_preco(linha)]


def desconsideradas(linhas: list[dict]) -> list[dict]:
    """Todas as outras — inclusive as marcadas que não puderam entrar."""
    dentro = {id(linha) for linha in consideradas(linhas)}
    return [linha for linha in linhas if id(linha) not in dentro]


def recalcular(linhas: list[dict], *, perfil: PerfilNormativo,
               regras: str, justificativa: str | None = None,
               metodo: str = estatistica.METODO_AUTOMATICO,
               criterio_percentual=None,
               mantidas: dict | None = None) -> estatistica.Estimativa:
    """
    Estimativa da cesta formada pelas linhas CONSIDERADAS.

    Só entra quem tem preço normalizado: referência sem conversão de
    unidade comprovada não compõe média nenhuma, mesmo marcada.
    """
    selecionadas = [referencia_da_linha(linha) for linha in linhas
                    if str(linha.get("status")) in NA_CESTA]
    com_preco = [r for r in selecionadas
                 if r.valor_unitario_normalizado is not None]
    de_preco = [r for r in com_preco if _compoe_cesta(r)]
    cesta = estatistica.Cesta(selecionadas=de_preco)
    if len(com_preco) < len(selecionadas):
        cesta.motivos.append(
            f"{len(selecionadas) - len(com_preco)} referência(s) marcada(s) "
            "sem preço normalizado (unidade não comprovada) ficaram fora "
            "do cálculo")
    if len(de_preco) < len(com_preco):
        cesta.motivos.append(
            f"{len(com_preco) - len(de_preco)} referência(s) marcada(s) com "
            "valor que não é preço praticado (ex.: estimativa de outro "
            "órgão) ficaram fora do cálculo")
    estimativa = estatistica.estimar(
        cesta, perfil=perfil, justificativa=justificativa, regras=regras,
        metodo=metodo, criterio_percentual=criterio_percentual,
        mantidas=mantidas)
    estimativa.memoria[:0] = cesta.motivos
    return estimativa


# ---------------------------------------------------------------------------
# Decisões humanas do item — método escolhido e exceção à regra dos três.
# Gravadas em `estatisticas.decisoes` e reaplicadas a cada recálculo.
# ---------------------------------------------------------------------------
def decisoes_do_item(item: dict) -> dict:
    gravado = item.get("estatisticas")
    if not isinstance(gravado, dict):
        return {}
    decisoes = gravado.get("decisoes")
    return dict(decisoes) if isinstance(decisoes, dict) else {}


def _agora() -> str:
    from datetime import datetime, timezone

    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _texto_da_excecao(excecao: dict) -> str:
    return (f"{excecao.get('texto', '').strip()} [fundamento: "
            f"{excecao.get('fundamento_texto') or excecao.get('fundamento')}"
            f"; base normativa: {excecao.get('base_normativa') or '—'}; "
            f"aprovação: {excecao.get('aprovador')}; registrada por "
            f"{excecao.get('registrado_por') or '—'} em "
            f"{excecao.get('registrado_em') or '—'}]")


def recalcular_e_gravar(pesquisa: dict, item: dict, repositorio, *,
                        perfil: PerfilNormativo, linhas: list[dict] | None = None,
                        revisao_esperada: int | None = None
                        ) -> estatistica.Estimativa:
    """
    Refaz a estimativa do item pela seleção gravada e persiste.

    O item fica em REVISÃO se a cesta fecha o perfil, INCOMPLETO se não
    fecha — a regra dos três vale igual depois da edição humana.

    As decisões humanas do item são reaplicadas: o método escolhido pelo
    revisor e a exceção à regra dos três. A exceção vale para a cesta
    em que foi registrada: se o número de preços considerados mudou, ela
    é INVALIDADA (fica no histórico do item com o motivo) e o item volta
    a pendente até nova justificativa.
    """
    if linhas is None:
        linhas = repositorio.listar_referencias(str(item["id"]))
    decisoes = decisoes_do_item(item)
    n = len(consideradas(linhas))
    justificativa = None
    excecao = decisoes.get("excecao")
    if excecao:
        if int(excecao.get("consideradas") or -1) == n and \
                n < perfil.minimo_referencias:
            justificativa = _texto_da_excecao(excecao)
        else:
            motivo = (f"a cesta mudou de {excecao.get('consideradas')} para "
                      f"{n} preço(s) considerado(s)")
            decisoes.setdefault("excecoes_anteriores", []).append(
                {**excecao, "invalidada_em": _agora(),
                 "motivo_invalidacao": motivo})
            decisoes.pop("excecao")
    metodo = (decisoes.get("metodo") or {}).get("metodo") or \
        estatistica.METODO_AUTOMATICO
    estimativa = recalcular(
        linhas, perfil=perfil,
        regras=str(pesquisa.get("versao_regras") or
                   estatistica.REGRAS_LEGADAS),
        justificativa=justificativa, metodo=metodo,
        criterio_percentual=estatistica.criterio_percentual_da(
            pesquisa.get("filtros")),
        mantidas=decisoes.get("mantidas") or None)
    metodo_decidido = decisoes.get("metodo")
    if metodo_decidido:
        estimativa.memoria.append(
            f"método definido pelo revisor: {metodo_decidido.get('metodo')} "
            f"— {metodo_decidido.get('justificativa')} "
            f"({metodo_decidido.get('registrado_por') or '—'}, "
            f"{metodo_decidido.get('registrado_em') or '—'})")
    repositorio.atualizar_estimativa(
        item, estimativa, quantidade=_decimal(item.get("quantidade")),
        decisoes=decisoes or None, revisao_esperada=revisao_esperada)
    return estimativa


def integridade_do_item(item: dict, linhas: list[dict], *,
                        teto: int | None = None) -> list[str]:
    """
    Invariantes do item na MESMA leitura (Revisão 02, 02_JEV "Invariantes
    em runtime"): consideradas ≤ na cesta ≤ gravadas; o N gravado no item
    é o N das linhas; total = unitário × quantidade; e, com `teto`, nunca
    mais consideradas que o teto da cotação automática.

    Devolve as violações em texto para quem decide o que fazer (a tela
    avisa, o teste falha) — não conserta nada sozinha: recalcular cesta
    antiga sem comando explícito é o que o roteiro proíbe.
    """
    problemas: list[str] = []
    n = len(consideradas(linhas))
    na_cesta = sum(1 for l in linhas if str(l.get("status")) in NA_CESTA)
    if not n <= na_cesta <= len(linhas):
        problemas.append(f"contagem incoerente: {n} consideradas, {na_cesta} "
                         f"na cesta, {len(linhas)} gravadas")
    gravado = na_cesta_do_item(item)
    if gravado is not None and gravado != n:
        problemas.append(f"o item registra {gravado} preço(s) considerado(s), "
                         f"mas a cesta tem {n}: recalcule o item")
    if teto is not None and n > teto:
        problemas.append(f"{n} preços na cesta, acima do limite de {teto} da "
                         "cotação automática (cesta formada antes do limite): "
                         "refaça a cotação automática deste item")
    unitario, quantidade = (_decimal(item.get("preco_estimado")),
                            _decimal(item.get("quantidade")))
    total = _decimal(item.get("preco_total"))
    if unitario is not None and quantidade is not None and total is not None:
        from decimal import ROUND_HALF_UP

        esperado = (unitario * quantidade).quantize(Decimal("0.01"),
                                                    rounding=ROUND_HALF_UP)
        if esperado != total.quantize(Decimal("0.01")):
            problemas.append(f"total gravado {total} difere de unitário × "
                             f"quantidade ({esperado})")
    return problemas


def itens_acima_do_teto(itens: list[dict], referencias: dict,
                        teto: int | None,
                        decididas_por_humano=None) -> list[str]:
    """
    Itens cuja cesta passa do teto da cotação automática — formada antes
    do limite e da triagem, por política que já não vale.

    Auditoria de 18/10/2026 (C-4): a pesquisa de 08/10 seguia emitível com
    cestas de 196, 317 e 270 preços, com papel A3, offset e grampeador
    cirúrgico dentro. O aviso de integridade só AVISAVA. A emissão pergunta
    aqui e não sai enquanto a lista não estiver vazia; a saída é refazer a
    cotação automática do item (nada é recalculado sozinho).

    Conta só o que a MÁQUINA escolheu: preço incluído por pessoa (evento
    de decisão ou cotação direta) é decisão do servidor e não trava nada
    — o mesmo critério da cotação automática (`cotacoes.de_pessoa`).
    `decididas_por_humano(item_id)` devolve os ids/id_externo decididos;
    só é chamada para item que já passou do teto.
    """
    if teto is None:
        return []
    acima = []
    for item in itens:
        linhas = consideradas(referencias.get(item.get("id"), []) or [])
        if len(linhas) <= teto:
            continue
        humanas = (set(decididas_por_humano(item.get("id")))
                   if decididas_por_humano is not None else set())
        da_maquina = [l for l in linhas
                      if str(l.get("fonte_id")) != "cotacao_direta"
                      and str(l.get("id")) not in humanas
                      and str(l.get("id_externo")) not in humanas]
        if len(da_maquina) > teto:
            acima.append(f"item {item.get('numero')}: {len(linhas)} preços "
                         f"na cesta (limite de {teto})")
    return acima


def contradicoes_na_cesta(itens: list[dict], referencias: dict,
                          decididas_por_humano=None) -> list[str]:
    """
    Itens cuja cesta GRAVADA tem preço de outro produto, pela barreira
    por atributo (`atributos.conflito`) aplicada na hora de emitir.

    Segunda auditoria de 18/10/2026 (N-01/N-04): a barreira da v1.9.8 só
    age quando a cotação automática roda, e as cestas formadas antes dela
    seguiam emitíveis — 298 de 983 preços contradiziam o item, o total de
    Material de Expediente ficava 16,2% acima, e "aquisição" passava no
    teto com 10 preços de outro produto. O teto mede tamanho; aqui se
    mede o conteúdo.

    Só CONTRADIZ trava (a fonte informa o atributo e ele difere do item);
    atributo ausente é conferência, não erro. Preço que uma PESSOA
    decidiu (evento de inclusão/exclusão ou cotação direta) não trava: o
    servidor discordou da barreira e isso está na trilha — o mesmo
    critério de `itens_acima_do_teto`. `decididas_por_humano(item_id)`
    só é chamada para item que tem contradição.
    """
    from . import atributos

    saida = []
    for item in itens:
        texto = str(item.get("descricao") or "")
        if not texto:
            continue
        achados = []
        for linha in consideradas(referencias.get(item.get("id"), []) or []):
            if str(linha.get("fonte_id")) == "cotacao_direta":
                continue
            achado = atributos.conflito(texto, linha.get("descricao_original"))
            if achado is not None and achado.tipo == atributos.CONTRADIZ:
                achados.append((linha, achado))
        if not achados:
            continue
        humanas = (set(decididas_por_humano(item.get("id")))
                   if decididas_por_humano is not None else set())
        achados = [(linha, achado) for linha, achado in achados
                   if str(linha.get("id")) not in humanas
                   and str(linha.get("id_externo")) not in humanas]
        if not achados:
            continue
        exemplos = list(dict.fromkeys(achado.motivo for _, achado in achados))
        saida.append(
            f"item {item.get('numero')}: {len(achados)} "
            f"{'preço' if len(achados) == 1 else 'preços'} de outro produto "
            f"na cesta ({'; '.join(exemplos[:2])}"
            f"{'; …' if len(exemplos) > 2 else ''})")
    return saida


def validas_na_cesta(linhas: list[dict]) -> int:
    """Quantas referências são consideradas no cálculo — o N de "N/3"."""
    return len(consideradas(linhas))


def na_cesta_do_item(item: dict) -> int | None:
    """
    O N de "N/3" a partir do que o item JÁ gravou (`estatisticas`), sem
    reler referências: a tabela de 210 itens não pode fazer 210 consultas
    para desenhar um indicador. `None` = o item ainda não foi pesquisado.
    """
    gravado = item.get("estatisticas")
    if not isinstance(gravado, dict):
        return None
    chave = "consideradas" if "consideradas" in gravado else "selecionadas"
    if chave not in gravado:
        return None
    try:
        return int(gravado[chave])
    except (TypeError, ValueError):
        return None


def indicador(item: dict, minimo: int = 3) -> str:
    """ "3/3 ✓", "2/3" ou "—" (não pesquisado)."""
    n = na_cesta_do_item(item)
    if n is None:
        return "—"
    return f"{n}/{minimo} ✓" if n >= minimo else f"{n}/{minimo}"


def pendencias_do_item(item: dict) -> list[str]:
    """As pendências de análise crítica que a estimativa gravada declarou."""
    gravado = item.get("estatisticas")
    if not isinstance(gravado, dict):
        return []
    return [str(p) for p in (gravado.get("pendencias") or [])]


MINIMO_JUSTIFICATIVA = 15


def validar_conclusao(item: dict, justificativa: str) -> str | None:
    """
    Concluir item com pendência de análise crítica exige justificativa —
    é o "manter com justificativa" do discrepante. Devolve o erro, ou None.
    """
    if pendencias_do_item(item) and \
            len(str(justificativa or "").strip()) < MINIMO_JUSTIFICATIVA:
        return ("Este item tem pendência de análise crítica. Retire os "
                "discrepantes da cesta ou justifique por que ela "
                "deve ser mantida como está.")
    return None


# ---------------------------------------------------------------------------
# Exceção à regra dos três (dossiê BP, temas 6a e J11; pacote, U05)
#
# O fluxo não existia: o perfil admitia concluir com menos de três, mas
# ninguém passava a justificativa ao cálculo, e o item ficava INCOMPLETO
# para sempre. Aqui ela é um ATO registrado, com quatro exigências:
#
#   1. o perfil precisa admitir (`admite_menos_com_justificativa`);
#   2. o item precisa ter ao menos UM preço considerado — exceção não
#      fabrica preço de item sem preço;
#   3. texto do gestor (mín. 15 caracteres) e fundamento escolhido;
#   4. a identificação de quem aprovou (autoridade competente) e a
#      declaração de que a aprovação consta dos autos. O GovConnect não
#      tem fluxo de aprovação de preço; ele REGISTRA a aprovação, não a
#      concede.
#
# Os modelos são orientação editável, nunca texto que afirme fato de
# mercado por conta própria; o servidor confirma e edita antes de gravar.
# ---------------------------------------------------------------------------
MODELOS_DE_JUSTIFICATIVA = {
    "mercado_restrito": (
        "Mercado restrito",
        "As fontes consultadas no período retornaram apenas {n} preço(s) "
        "comparável(is) para a especificação exigida; a ampliação da busca "
        "trouxe somente produtos não equivalentes."),
    "especificacao_singular": (
        "Especificação singular",
        "As características técnicas exigidas para o item reduzem as "
        "contratações comparáveis a {n} referência(s) válida(s); produtos "
        "de especificação inferior não servem de parâmetro."),
    "complemento_documentado": (
        "Complemento por outro meio",
        "Além dos {n} preço(s) considerado(s), a estimativa é sustentada por "
        "documento juntado aos autos (indique qual: cotação direta, ata de "
        "registro de preços ou outro)."),
    "outro": ("Outro fundamento", ""),
}

ESCOPOS = ("item", "selecionados", "todos")


class ExcecaoInvalida(ValueError):
    """A exceção não pode ser registrada — a mensagem diz o que falta."""


def modelo_de_justificativa(chave: str, n: int) -> str:
    _, texto = MODELOS_DE_JUSTIFICATIVA.get(chave, ("", ""))
    return texto.format(n=n)


def validar_excecao(item: dict, linhas: list[dict], *,
                    perfil: PerfilNormativo, texto: str, fundamento: str,
                    aprovador: str, aprovacao_declarada: bool = True) -> int:
    """Devolve o N considerado, ou levanta dizendo o que impede."""
    if not perfil.admite_menos_com_justificativa:
        raise ExcecaoInvalida(
            f"o perfil {perfil.nome} não admite concluir com menos de "
            f"{perfil.minimo_referencias} preços")
    n = len(consideradas(linhas))
    if n == 0:
        raise ExcecaoInvalida(
            "o item não tem nenhum preço considerado — a exceção não forma "
            "preço; amplie a busca ou registre cotação direta")
    if n >= perfil.minimo_referencias:
        raise ExcecaoInvalida(
            f"o item já tem {n} preços considerados; não precisa de exceção")
    if fundamento not in MODELOS_DE_JUSTIFICATIVA:
        raise ExcecaoInvalida("escolha o fundamento da exceção")
    if len(str(texto or "").strip()) < MINIMO_JUSTIFICATIVA:
        raise ExcecaoInvalida(
            "escreva a justificativa do gestor (ao menos 15 caracteres)")
    if len(str(aprovador or "").strip()) < 3:
        raise ExcecaoInvalida(
            "identifique a autoridade competente que aprovou a exceção")
    if not aprovacao_declarada:
        raise ExcecaoInvalida(
            "confirme que a aprovação da autoridade competente consta dos "
            "autos")
    return n


def registrar_excecao(pesquisa: dict, item: dict, repositorio, *,
                      perfil: PerfilNormativo, texto: str, fundamento: str,
                      aprovador: str, ator: str | None = None,
                      aprovacao_declarada: bool = True, escopo: str = "item",
                      revisao_esperada: int | None = None
                      ) -> estatistica.Estimativa:
    """
    Registra a exceção do item e refaz a estimativa com ela.

    O item sai de INCOMPLETO para REVISÃO — ainda não é COMPLETO: quem
    conclui é o revisor, depois de ler a memória com a exceção impressa.
    """
    linhas = repositorio.listar_referencias(str(item["id"]))
    n = validar_excecao(item, linhas, perfil=perfil, texto=texto,
                        fundamento=fundamento, aprovador=aprovador,
                        aprovacao_declarada=aprovacao_declarada)
    decisoes = decisoes_do_item(item)
    anterior = decisoes.get("excecao")
    if anterior:
        decisoes.setdefault("excecoes_anteriores", []).append(
            {**anterior, "substituida_em": _agora()})
    rotulo, _ = MODELOS_DE_JUSTIFICATIVA[fundamento]
    decisoes["excecao"] = {
        "texto": str(texto).strip(), "fundamento": fundamento,
        "fundamento_texto": rotulo, "base_normativa": perfil.fundamento_excecao,
        "aprovador": str(aprovador).strip(), "aprovacao_declarada": True,
        "registrado_por": ator, "registrado_em": _agora(),
        "consideradas": n, "perfil": perfil.id, "escopo": escopo,
    }
    estimativa = recalcular_e_gravar(
        pesquisa, {**item, "estatisticas": {
            **(item.get("estatisticas") or {}), "decisoes": decisoes}},
        repositorio, perfil=perfil, linhas=linhas,
        revisao_esperada=revisao_esperada)
    repositorio.registrar_evento(
        str(pesquisa["id"]), "excecao_registrada", ator=ator,
        item_id=str(item["id"]), descricao=str(texto).strip(),
        payload={"fundamento": fundamento, "aprovador": str(aprovador).strip(),
                 "consideradas": n, "minimo": perfil.minimo_referencias,
                 "escopo": escopo, "base_normativa": perfil.fundamento_excecao,
                 "preco_recalculado": None if estimativa.valor_unitario is None
                 else format(estimativa.valor_unitario, "f")})
    return estimativa


def prever_excecao_em_lote(itens: list[dict], referencias: dict[str, list[dict]],
                           *, perfil: PerfilNormativo, escopo: str,
                           selecionados: set[str] | None = None,
                           sobrescrever: bool = False) -> list[dict]:
    """
    A PRÉVIA da aplicação em lote: quem recebe a exceção e quem não, com
    o motivo. Nada é gravado aqui — o servidor confirma sobre esta lista.
    """
    if escopo not in ESCOPOS:
        raise ExcecaoInvalida("escopo desconhecido")
    alvo = itens
    if escopo == "selecionados":
        alvo = [i for i in itens if str(i.get("id")) in (selecionados or set())]
    previa = []
    for item in alvo:
        n = len(consideradas(referencias.get(str(item.get("id")), [])))
        tem = bool(decisoes_do_item(item).get("excecao"))
        if str(item.get("estado")) == "complete":
            situacao = "já concluído"
        elif n == 0:
            situacao = "sem preço considerado — não recebe exceção"
        elif n >= perfil.minimo_referencias:
            situacao = "já tem o mínimo — não precisa"
        elif tem and not sobrescrever:
            situacao = "já tem exceção — mantida"
        else:
            situacao = "recebe a exceção"
        previa.append({"item_id": str(item.get("id")),
                       "numero": int(item.get("numero") or 0),
                       "descricao": str(item.get("descricao") or ""),
                       "consideradas": n, "situacao": situacao,
                       "aplica": situacao == "recebe a exceção"})
    return previa


def aplicar_excecao_em_lote(pesquisa: dict, itens: list[dict], repositorio, *,
                            previa: list[dict], perfil: PerfilNormativo,
                            fundamento: str, texto_modelo: str, aprovador: str,
                            ator: str | None = None, escopo: str = "todos"
                            ) -> list[tuple[dict, str]]:
    """Aplica a exceção aos itens que a prévia marcou. Devolve (item, resultado)."""
    por_id = {str(i.get("id")): i for i in itens}
    saida = []
    for linha in previa:
        if not linha.get("aplica"):
            continue
        item = por_id[linha["item_id"]]
        texto = texto_modelo.replace("{n}", str(linha["consideradas"]))
        try:
            registrar_excecao(pesquisa, item, repositorio, perfil=perfil,
                              texto=texto, fundamento=fundamento,
                              aprovador=aprovador, ator=ator, escopo=escopo)
            saida.append((item, "exceção registrada"))
        except ExcecaoInvalida as erro:
            saida.append((item, f"não aplicada: {erro}"))
    return saida


# ---------------------------------------------------------------------------
# Método do item escolhido pelo revisor (dossiê BP, tema 5a/5b)
# ---------------------------------------------------------------------------
METODOS_ROTULO = {"automatico": "padrão da cotação", "media": "média aritmética",
                  "mediana": "mediana", "menor": "menor preço"}


def escolher_metodo(pesquisa: dict, item: dict, repositorio, *,
                    perfil: PerfilNormativo, metodo: str, justificativa: str,
                    ator: str | None = None,
                    revisao_esperada: int | None = None
                    ) -> estatistica.Estimativa:
    """
    Troca o método do item, com justificativa, e refaz o preço.

    "automatico" volta ao padrão da cotação (sem justificativa). Método
    que o perfil não admite é recusado aqui — a estimativa nunca cai em
    outro método em silêncio.
    """
    decisoes = decisoes_do_item(item)
    if metodo == estatistica.METODO_AUTOMATICO:
        decisoes.pop("metodo", None)
    else:
        if metodo not in perfil.metodos_permitidos:
            raise ValueError(
                f"o perfil {perfil.nome} admite: "
                f"{', '.join(perfil.metodos_permitidos)}")
        if len(str(justificativa or "").strip()) < MINIMO_JUSTIFICATIVA:
            raise ValueError("justifique a troca do método (mín. 15 caracteres)")
        decisoes["metodo"] = {"metodo": metodo,
                              "justificativa": str(justificativa).strip(),
                              "registrado_por": ator,
                              "registrado_em": _agora()}
    estimativa = recalcular_e_gravar(
        pesquisa, {**item, "estatisticas": {
            **(item.get("estatisticas") or {}), "decisoes": decisoes}},
        repositorio, perfil=perfil, revisao_esperada=revisao_esperada)
    repositorio.registrar_evento(
        str(pesquisa["id"]), "metodo_alterado", ator=ator,
        item_id=str(item["id"]), descricao=str(justificativa or "").strip(),
        payload={"metodo": metodo, "aplicado": estimativa.metodo,
                 "preco_recalculado": None if estimativa.valor_unitario is None
                 else format(estimativa.valor_unitario, "f")})
    return estimativa


def discrepantes(linhas: list[dict], *, perfil: PerfilNormativo,
                 regras: str) -> list[tuple[dict, str]]:
    """
    `(linha, critério)` das referências DA CESTA que o detector sinaliza
    agora, sobre a seleção gravada. Só aponta: quem exclui é o revisor.
    """
    estimativa = recalcular(linhas, perfil=perfil, regras=regras)
    por_chave = {(str(linha.get("fonte_id") or ""),
                  str(linha.get("id_externo") or "")): linha
                 for linha in linhas}
    saida = []
    # do mais distante da mediana para o menos: o erro grosseiro primeiro
    for anomalia in sorted(estimativa.anomalias,
                           key=lambda a: -abs(a.distancia_da_mediana_pct)):
        chave = (anomalia.referencia.fonte.id, anomalia.referencia.id_externo)
        if chave in por_chave:
            saida.append((por_chave[chave], anomalia.criterio))
    return saida


def excluir_discrepantes(pesquisa: dict, item: dict, repositorio, *,
                         perfil: PerfilNormativo, motivo: str | None = None,
                         ator: str | None = None) -> estatistica.Estimativa:
    """
    O ato HUMANO de excluir, de uma vez, os discrepantes sinalizados. O
    critério estatístico de cada um é registrado na referência — é a
    fundamentação técnica, sempre presente; o motivo do revisor é
    OPCIONAL (pacote Jev, RF-02) e, quando dado, vai junto. Depois refaz
    o preço. A série menor pode revelar outro discrepante: ele será
    sinalizado, não excluído — cada exclusão é um clique de alguém.
    """
    texto = str(motivo or "").strip()
    regras = str(pesquisa.get("versao_regras") or estatistica.REGRAS_LEGADAS)
    linhas = repositorio.listar_referencias(str(item["id"]))
    alvos = discrepantes(linhas, perfil=perfil, regras=regras)
    for linha, criterio in alvos:
        repositorio.reclassificar_referencia(
            str(linha["id"]), "rejected",
            (f"{texto} " if texto else "retirada da cesta pelo usuário ")
            + f"(sinalizada pelo critério {criterio})")
    estimativa = recalcular_e_gravar(pesquisa, item, repositorio,
                                     perfil=perfil)
    repositorio.registrar_evento(
        str(pesquisa["id"]), "referencia_excluida", ator=ator,
        item_id=str(item["id"]),
        descricao=texto or "discrepantes sinalizados retirados da cesta "
                           "pelo usuário",
        payload={"referencias": [str(linha["id"]) for linha, _ in alvos],
                 "lote": "discrepantes", "operacao": "manual_removed",
                 "origem": "user", "user_reason": texto or None,
                 "preco_recalculado": None if estimativa.valor_unitario is None
                 else format(estimativa.valor_unitario, "f"),
                 "metodo": estimativa.metodo,
                 "status_da_cesta": estimativa.status,
                 "pendencias": list(estimativa.pendencias)})
    return estimativa


ESTADOS_RECALCULAVEIS = frozenset({EstadoItem.EM_REVISAO.value,
                                   EstadoItem.INCOMPLETO.value})


def salvar_consulta_como_pesquisa(
        *, repositorio, nome: str, item: dict, coleta, selecionados: set[str],
        perfil: PerfilNormativo, auth_user_id: str,
        secretaria_id: str | None = None, processo_id: str | None = None,
        filtros: dict | None = None, idempotency_key: str = "") -> dict:
    """
    A consulta do Banco de Preços vira uma pesquisa — a MESMA entidade da
    Pesquisa Automática, com o mesmo item, referências, cesta, relatórios
    e aplicação ao processo. Não há "pesquisa manual" paralela.

    `selecionados` são as chaves (`fonte:id_externo`) que o servidor
    marcou; as demais candidatas também são gravadas, para que a
    revisão mostre o que foi visto e não escolhido. O item percorre as
    mesmas transições do motor (pendente → buscando → classificando →
    revisão/incompleto): nada pula a máquina de estados.
    """
    from .estados import EstadoPesquisa
    from .modelo import StatusReferencia

    # Duplo clique / rerun não cria segunda pesquisa: a mesma chave
    # devolve a que já existe.
    if idempotency_key:
        existente = repositorio.obter_por_chave(idempotency_key)
        if existente:
            return {"pesquisa_id": str(existente["id"]), "item_id": None,
                    "estimativa": None, "reaproveitada": True}

    pesquisa = repositorio.criar_pesquisa(
        nome, auth_user_id=auth_user_id, secretaria_id=secretaria_id,
        processo_id=processo_id, perfil_normativo=perfil.id,
        filtros=dict(filtros or {}),
        versao_regras=estatistica.REGRAS_MEDIA_PADRAO,
        idempotency_key=idempotency_key)
    pesquisa_id = str(pesquisa["id"])
    [linha_item] = repositorio.salvar_itens(pesquisa_id, [{
        "numero": 1, "codigo": item.get("codigo") or None,
        "tipo_catalogo": item.get("tipo_catalogo") or None,
        "descricao": item["descricao"], "unidade": item.get("unidade") or "",
        "quantidade": item.get("quantidade")}])
    item_id = str(linha_item["id"])

    # A tela manda chaves; quem decide se a chave pode compor cesta é o
    # servidor. Natureza não comparável ou unidade não comprovada ficam
    # CANDIDATAS mesmo que venham marcadas.
    for referencia, _comp in coleta.referencias:
        apta = (referencia.chave_dedupe in selecionados
                and referencia.valor_unitario_normalizado is not None
                and referencia.serve_de_preco)
        referencia.status = (StatusReferencia.SELECIONADA if apta
                             else StatusReferencia.CANDIDATA)
    escolhidas = sum(1 for r, _ in coleta.referencias
                     if r.status is StatusReferencia.SELECIONADA)
    repositorio.mover_pesquisa(pesquisa_id, EstadoPesquisa.NA_FILA,
                               EstadoPesquisa.RASCUNHO)
    repositorio.mover_pesquisa(pesquisa_id, EstadoPesquisa.EXECUTANDO,
                               EstadoPesquisa.NA_FILA)
    repositorio.mover_item(item_id, EstadoItem.BUSCANDO, EstadoItem.PENDENTE)
    repositorio.registrar_referencias(item_id, coleta.referencias)
    repositorio.mover_item(item_id, EstadoItem.CLASSIFICANDO,
                           EstadoItem.BUSCANDO)

    linhas = repositorio.listar_referencias(item_id)
    estimativa = recalcular(linhas, perfil=perfil,
                            regras=estatistica.REGRAS_MEDIA_PADRAO)
    repositorio.registrar_estimativa(
        item_id, estimativa, atual=EstadoItem.CLASSIFICANDO,
        quantidade=_decimal(item.get("quantidade")))
    destino = (EstadoPesquisa.EM_REVISAO if estimativa.concluida
               else EstadoPesquisa.PARCIAL)
    repositorio.mover_pesquisa(pesquisa_id, destino, EstadoPesquisa.EXECUTANDO)
    repositorio.registrar_evento(
        pesquisa_id, "pesquisa_criada", ator=auth_user_id,
        descricao=f"Banco de Preços: consulta salva com "
                  f"{escolhidas} referência(s) escolhida(s) de "
                  f"{coleta.unicas} encontrada(s)",
        payload={"origem": "banco_de_precos", "brutas": coleta.brutas,
                 "unicas": coleta.unicas, "selecionadas": escolhidas,
                 "valor": None if estimativa.valor_unitario is None
                 else format(estimativa.valor_unitario, "f")})
    return {"pesquisa_id": pesquisa_id, "item_id": item_id,
            "estimativa": estimativa}
