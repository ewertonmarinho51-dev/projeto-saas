"""
Execução da pesquisa em LOTES REENTRANTES.

O problema, medido na Fase 0: não existe infraestrutura de jobs neste
projeto — nenhuma ocorrência de `threading`, `asyncio`, `celery`, `rq`,
`multiprocessing` ou `concurrent.futures` em `src/`. Tudo roda síncrono
dentro do script run do Streamlit. Com 210 itens e ~1 s por chamada
externa, uma pesquisa completa congelaria a interface por minutos, o que
o §46 proíbe.

A solução escolhida — e o §46 manda escolher explicitamente em vez de
introduzir infraestrutura em silêncio — é a **opção 1 da Fase 0**: cada
script run processa um LOTE PEQUENO de itens, grava o resultado no
banco e devolve o controle. A interface chama `st.rerun()` e o lote
seguinte começa. O progresso não mora em memória: mora no `estado` de
cada item, que já é persistido.

Isso entrega os cinco requisitos do §19 sem servidor novo:

* **checkpoint** — o estado de cada item é a marca d'água; o que já
  concluiu não é refeito;
* **retomada** — reabrir a pesquisa amanhã continua de onde parou,
  inclusive em outra máquina, porque o checkpoint é do banco e não da
  sessão;
* **retry** — item em `error` volta para a fila na rodada seguinte;
* **cancelamento** — é uma transição de estado da pesquisa, não uma
  `thread` a matar;
* **idempotência** — reprocessar o mesmo item faz `upsert` nas
  referências pela chave (item, fonte, id externo). A amostra não dobra.

O custo honesto: é mais lento que paralelizar, e cada lote paga um
rerun. Em troca, nada se perde se o navegador fechar no meio.

Este módulo é **lógica pura**: não importa Streamlit. Quem chama decide
quando rodar o próximo lote — o que o torna testável sem interface e
reutilizável por um worker externo, se um dia existir.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from datetime import date, timedelta
from decimal import Decimal, InvalidOperation

from . import estatistica, matching, unidades
from .estados import EstadoItem, EstadoPesquisa, estado_derivado
from . import fontes as fontes_mod
from .fontes import Consulta, Desfecho, FontePesquisaPreco
from .modelo import Referencia, conferir_procedencia, deduplicar
from .perfil import PADRAO, PerfilNormativo

# Quantos itens por script run.
#
# Não é número mágico: é o maior lote que ainda devolve a interface em
# tempo aceitável. Cada item custa ~1 s por fonte, então 5 itens × 2
# fontes ≈ 10 s de espera por rerun — perceptível, mas dentro do que uma
# barra de progresso sustenta. Lote maior congela; lote menor multiplica
# reruns e fica mais lento no total.
LOTE_PADRAO = 5

# Janela temporal padrão da consulta. Preço de dois anos atrás não
# descreve o mercado de hoje; abrir demais enche a amostra de referência
# velha que o fator de temporalidade vai penalizar de qualquer modo.
JANELA_PADRAO_DIAS = 365

# Quantas referências pedir por item a cada fonte.
LIMITE_POR_FONTE = 100


@dataclass
class Progresso:
    """
    Retrato da execução, derivado do BANCO e não de memória.

    É o que a tela do §19 mostra ("Item 01 ✓ 8 preços encontrados") e é o
    que permite fechar o navegador sem perder nada.
    """

    total: int = 0
    concluidos: int = 0        # complete
    incompletos: int = 0       # incomplete
    em_revisao: int = 0        # review
    com_erro: int = 0          # error
    pendentes: int = 0         # pending/searching/matching

    @property
    def processados(self) -> int:
        return self.total - self.pendentes

    @property
    def terminou(self) -> bool:
        return self.pendentes == 0

    @property
    def fracao(self) -> float:
        """0.0–1.0 para a barra. Pesquisa sem item não é 0%, é 100%."""
        return 1.0 if not self.total else self.processados / self.total

    def resumo(self) -> str:
        partes = [f"{self.processados} de {self.total}"]
        if self.incompletos:
            partes.append(f"{self.incompletos} incompleto(s)")
        if self.com_erro:
            partes.append(f"{self.com_erro} com erro")
        return " — ".join(partes)


def progresso_de(itens: list[dict]) -> Progresso:
    """Conta os estados dos itens. Uma passada, sem consultar de novo."""
    p = Progresso(total=len(itens))
    for item in itens:
        estado = str(item.get("estado") or EstadoItem.PENDENTE.value)
        if estado == EstadoItem.COMPLETO.value:
            p.concluidos += 1
        elif estado == EstadoItem.INCOMPLETO.value:
            p.incompletos += 1
        elif estado == EstadoItem.EM_REVISAO.value:
            p.em_revisao += 1
        elif estado == EstadoItem.ERRO.value:
            p.com_erro += 1
        else:
            p.pendentes += 1
    return p


# ---------------------------------------------------------------------------
# Fila
# ---------------------------------------------------------------------------
# Estados que a rodada seguinte deve pegar. `error` está aqui porque é o
# RETRY do §19: falha técnica volta para a fila. `incomplete` NÃO está —
# ele já rodou e o mercado não tinha referência bastante; refazer sozinho
# gastaria a API para chegar ao mesmo lugar. Quem decide repetir um
# incompleto é o revisor, com "Buscar mais".
A_PROCESSAR = frozenset({
    EstadoItem.PENDENTE.value, EstadoItem.BUSCANDO.value,
    EstadoItem.CLASSIFICANDO.value, EstadoItem.ERRO.value,
})


def proximo_lote(itens: list[dict], tamanho: int = LOTE_PADRAO) -> list[dict]:
    """
    Os próximos itens a processar, na ordem da planilha.

    Ordem estável de propósito: o servidor acompanha a barra vendo o
    item 1, 2, 3… Uma fila embaralhada faria o progresso parecer
    aleatório e tornaria impossível dizer onde parou.
    """
    fila = [i for i in itens
            if str(i.get("estado") or EstadoItem.PENDENTE.value) in A_PROCESSAR]
    fila.sort(key=lambda i: int(i.get("numero") or 0))
    return fila[:max(1, tamanho)]


def _decimal(valor) -> Decimal | None:
    if valor is None or valor == "":
        return None
    try:
        return Decimal(str(valor))
    except (InvalidOperation, ValueError, TypeError):
        return None


def consulta_do_item(item: dict, filtros: dict | None = None,
                     termos_alternativos: tuple[str, ...] = ()) -> Consulta:
    """
    Traduz a linha do banco para a `Consulta` que os adapters entendem.

    A janela temporal entra aqui, e não no adapter, porque é decisão da
    PESQUISA (fica gravada em `filtros` e vai para o relatório), não da
    fonte.
    """
    filtros = filtros or {}
    quantidade = _decimal(item.get("quantidade"))
    hoje = filtros.get("data_base") or date.today()
    if isinstance(hoje, str):
        hoje = date.fromisoformat(hoje[:10])
    dias = int(filtros.get("janela_dias") or JANELA_PADRAO_DIAS)
    return Consulta(
        descricao=str(item.get("descricao") or ""),
        unidade=item.get("unidade") or None,
        quantidade=float(quantidade) if quantidade is not None else None,
        codigo_catalogo=item.get("codigo") or None,
        tipo_catalogo=item.get("tipo_catalogo") or None,
        material_ou_servico=("S" if item.get("tipo_catalogo") == "CATSER"
                             else "M"),
        uf=filtros.get("uf") or None,
        data_inicial=hoje - timedelta(days=dias),
        data_final=hoje,
        limite=int(filtros.get("limite") or LIMITE_POR_FONTE),
        termos_alternativos=tuple(termos_alternativos),
    )


@dataclass
class ResultadoItem:
    """
    O que uma rodada produziu para um item.

    Carrega a `Estimativa` E as ocorrências das fontes: o §37 exige que
    "PNCP indisponível" apareça para o usuário em vez de sumir, e o §38
    quer isso na observabilidade.
    """

    item_id: str
    numero: int
    referencias: list[tuple[Referencia, matching.Comparabilidade]] = field(
        default_factory=list)
    estimativa: estatistica.Estimativa | None = None
    ocorrencias: list[str] = field(default_factory=list)
    encontradas: int = 0
    erro: str = ""
    duracao_s: float = 0.0

    # Termos que a camada semântica sugeriu, quando havia motor. Vai ao
    # relatório: o §58 exige poder responder depois "o que a IA fez
    # nesta pesquisa", e a resposta honesta é uma lista de palavras.
    termos_semanticos: list[str] = field(default_factory=list)

    # Desfecho de CADA fonte consultada, por id. É o que permite ao
    # relatório e à tela dizerem "o Compras.gov caiu; o PNCP respondeu"
    # em vez de um "houve problemas" que não ajuda ninguém a decidir se
    # vale repetir a busca.
    desfechos: dict[str, str] = field(default_factory=dict)

    @property
    def falhou(self) -> bool:
        return bool(self.erro)

    @property
    def fontes_de_preco_falharam(self) -> list[str]:
        return [fid for fid, d in self.desfechos.items()
                if d == Desfecho.FALHA.value and fid in self._de_preco]

    # Preenchido por `pesquisar_item`: quais dos ids consultados eram
    # fontes de preço. Sem isso, `desfechos` sozinho não diz se a falha
    # atingiu quem importa.
    _de_preco: frozenset = field(default_factory=frozenset, repr=False)


def pesquisar_item(item: dict, fontes: list[FontePesquisaPreco], *,
                   perfil: PerfilNormativo = PADRAO,
                   filtros: dict | None = None,
                   piso: Decimal | None = None,
                   motor_semantico=None) -> ResultadoItem:
    """
    O pipeline de um item, do zero à estimativa.

    Coletar → deduplicar → normalizar unidade → ranquear por
    comparabilidade → montar cesta → estimar. Nenhuma dessas etapas
    inventa nada: o que não se prova fica `None` com o motivo, e a
    estimativa sai `INCOMPLETO` em vez de sair com preço fabricado.

    **Falha de fonte não derruba o item** (§37). Cada adapter é chamado
    dentro do seu próprio `try`, e uma exceção vira ocorrência
    registrada — a pesquisa segue com as demais fontes. Só se TODAS
    falharem o item vai para `error`.
    """
    filtros = filtros or {}
    inicio = time.monotonic()
    resultado = ResultadoItem(item_id=str(item.get("id") or ""),
                              numero=int(item.get("numero") or 0))

    # ------------------------------------------------------------------
    # A IA entra AQUI, e some em seguida
    # ------------------------------------------------------------------
    # É o único ponto do fluxo automático em que a camada semântica toca
    # a pesquisa, e o que ela produz são PALAVRAS. Ela não vê preço — o
    # prompt não o carrega —, não pontua referência, não escolhe cesta e
    # não calcula nada. Da linha seguinte em diante tudo é
    # determinístico.
    #
    # O pior estrago que um termo ruim causa é trazer candidato
    # irrelevante, que o matching descarta. Nunca um preço errado.
    #
    # Sem motor a lista sai vazia e o pipeline segue idêntico: a camada é
    # opcional de verdade, não um caminho feliz com fallback improvisado.
    from . import semantica
    termos = tuple(semantica.sugerir_termos(motor_semantico, item))
    if termos:
        resultado.termos_semanticos = list(termos)
        resultado.ocorrencias.append(
            "busca ampliada com termos equivalentes sugeridos pela camada "
            f"semântica: {', '.join(termos)}")

    consulta = consulta_do_item(item, filtros, termos)

    coletadas: list[Referencia] = []
    de_preco: set[str] = set()
    for fonte in fontes:
        fid = getattr(getattr(fonte, "fonte", None), "id", "") or repr(fonte)
        nome = getattr(getattr(fonte, "fonte", None), "nome", "fonte")
        if fontes_mod.fornece_preco(fonte):
            de_preco.add(fid)
        try:
            busca = fonte.pesquisar(consulta)
        except Exception as exc:  # noqa: BLE001 — adapter nenhum derruba a pesquisa
            resultado.desfechos[fid] = Desfecho.FALHA.value
            resultado.ocorrencias.append(
                f"{nome}: indisponível no momento ({type(exc).__name__})")
            continue
        resultado.desfechos[fid] = busca.desfecho.value
        coletadas.extend(busca.referencias)
        resultado.ocorrencias.extend(busca.ocorrencias)

    resultado._de_preco = frozenset(de_preco)

    # ------------------------------------------------------------------
    # Falha técnica NÃO é amostra insuficiente
    # ------------------------------------------------------------------
    # A versão anterior contava exceções: `falhas == len(fontes)`. Dois
    # buracos, e os dois produziam a mesma mentira na tela.
    #
    # 1. adapter que trata o erro por dentro — e os dois tratam — nunca
    #    levantava exceção. Um HTTP 503 do Compras.gov virava
    #    `ResultadoBusca` vazio, `falhas` continuava 0, e o item saía
    #    `incomplete`: "o mercado não tinha este item". O mercado não
    #    tinha nada a ver com isso;
    # 2. contava TODAS as fontes. Com o PNCP de pé (evidência) e o
    #    Compras.gov fora (preço), `falhas != len(fontes)` e a pesquisa
    #    se dizia bem-sucedida — apesar de nenhuma fonte de preço ter
    #    respondido.
    #
    # A conta certa é sobre as fontes CAPAZES DE FORNECER PREÇO. Se
    # todas elas falharam, é falha técnica: o item volta para a fila e se
    # repete. Se responderam e não trouxeram nada, aí sim é o mercado
    # falando, e repetir amanhã dá o mesmo.
    falharam = [fid for fid in de_preco
                if resultado.desfechos.get(fid) == Desfecho.FALHA.value]
    if de_preco and len(falharam) == len(de_preco):
        resultado.erro = (
            "as fontes de preço não responderam "
            f"({', '.join(sorted(falharam))}) — isto é falha técnica, não "
            "ausência de preço no mercado; o item volta para a fila")
        resultado.duracao_s = time.monotonic() - inicio
        return resultado

    if not de_preco:
        # Nenhuma fonte de preço configurada. Também é falha técnica, e
        # de configuração: sem ela a pesquisa não pode dar certo nunca, e
        # deixar sair `incomplete` culparia o mercado por um erro nosso.
        resultado.erro = (
            "nenhuma fonte capaz de fornecer preço foi configurada para "
            "esta pesquisa")
        resultado.duracao_s = time.monotonic() - inicio
        return resultado

    # A procedência é conferida ANTES de qualquer outra coisa: é aqui
    # que o dado externo deixa de ser "o que a fonte disse ser" e passa
    # a ser o que o módulo aceita. Uma fonte não registrada que se
    # declarasse sistema oficial entraria na cesta à frente de uma
    # contratação similar verdadeira (§55).
    unicas = conferir_procedencia(deduplicar(coletadas))
    resultado.encontradas = len(unicas)

    unidade = str(item.get("unidade") or "")
    normalizadas = [unidades.normalizar(r, unidade) for r in unicas]

    data_base = filtros.get("data_base")
    if isinstance(data_base, str):
        data_base = date.fromisoformat(data_base[:10])
    ranqueadas = matching.ordenar_por_comparabilidade(
        normalizadas,
        descricao=str(item.get("descricao") or ""),
        codigo_catalogo=item.get("codigo") or None,
        quantidade=_decimal(item.get("quantidade")),
        uf=filtros.get("uf") or None,
        data_base=data_base,
    )
    resultado.referencias = ranqueadas

    cesta = estatistica.selecionar_cesta(
        ranqueadas, perfil,
        piso if piso is not None else estatistica.PISO_COMPARABILIDADE)
    resultado.estimativa = estatistica.estimar(
        cesta, perfil=perfil,
        metodo=str(filtros.get("metodo") or estatistica.METODO_AUTOMATICO))
    resultado.duracao_s = time.monotonic() - inicio
    return resultado


# ---------------------------------------------------------------------------
# Rodada — a ponte com a persistência
# ---------------------------------------------------------------------------
def executar_lote(pesquisa: dict, itens: list[dict],
                  fontes: list[FontePesquisaPreco], repositorio, *,
                  perfil: PerfilNormativo = PADRAO,
                  tamanho: int = LOTE_PADRAO,
                  motor_semantico=None) -> tuple[Progresso, list[str]]:
    """
    Processa um lote e PERSISTE. Devolve (progresso, linhas do relato).

    `repositorio` é injetado em vez de importado para que o motor possa
    ser exercitado sem banco — e para deixar visível que este módulo não
    conhece Supabase, só a interface do repositório.

    A ordem das escritas importa e não é acidental:

    1. o item vai para `searching` ANTES da chamada externa. Se o
       processo morrer no meio, o checkpoint mostra onde parou;
    2. as referências são gravadas ANTES da estimativa. Uma queda entre
       as duas deixa o item com as referências no banco e o estado ainda
       de trabalho — a rodada seguinte o refaz, e o `upsert` não duplica;
    3. a estimativa e o estado final vão na MESMA escrita
       (`registrar_estimativa`), para não existir item `review` sem
       preço para revisar.
    """
    filtros = dict(pesquisa.get("filtros") or {})
    lote = proximo_lote(itens, tamanho)
    relato: list[str] = []
    por_id = {str(i.get("id")): i for i in itens}

    for item in lote:
        item_id = str(item.get("id"))
        estado_atual = str(item.get("estado") or EstadoItem.PENDENTE.value)
        try:
            repositorio.mover_item(item_id, EstadoItem.BUSCANDO, estado_atual)
            por_id[item_id]["estado"] = EstadoItem.BUSCANDO.value

            resultado = pesquisar_item(item, fontes, perfil=perfil,
                                       filtros=filtros,
                                       motor_semantico=motor_semantico)

            if resultado.falhou:
                # `desfechos` e `erro` são gravados junto do estado: sem
                # eles, ao recarregar a pesquisa amanhã ninguém distingue
                # "a fonte de preço caiu" de "o mercado não tinha o
                # item" — e só o primeiro caso justifica repetir a busca.
                repositorio.mover_item(item_id, EstadoItem.ERRO,
                                       EstadoItem.BUSCANDO,
                                       ocorrencias=resultado.ocorrencias,
                                       desfechos=resultado.desfechos,
                                       erro=resultado.erro)
                por_id[item_id]["estado"] = EstadoItem.ERRO.value
                relato.append(
                    f"Item {resultado.numero:02d}  !  {resultado.erro}")
                continue

            if resultado.referencias:
                repositorio.registrar_referencias(item_id,
                                                  resultado.referencias)

            repositorio.mover_item(item_id, EstadoItem.CLASSIFICANDO,
                                   EstadoItem.BUSCANDO)
            linha = repositorio.registrar_estimativa(
                item_id, resultado.estimativa,
                atual=EstadoItem.CLASSIFICANDO,
                quantidade=_decimal(item.get("quantidade")))
            por_id[item_id].update(linha or {})
            relato.append(_relato(resultado))

        except Exception as exc:  # noqa: BLE001 — um item ruim não para o lote
            try:
                repositorio.mover_item(
                    item_id, EstadoItem.ERRO,
                    por_id[item_id].get("estado") or estado_atual)
                por_id[item_id]["estado"] = EstadoItem.ERRO.value
            except Exception:  # noqa: BLE001 — já estamos no caminho de erro
                pass
            relato.append(
                f"Item {int(item.get('numero') or 0):02d}  !  "
                f"falha ao processar ({type(exc).__name__})")

    return progresso_de(list(por_id.values())), relato


def _relato(resultado: ResultadoItem) -> str:
    """Uma linha no formato do §19: `Item 01  ✓  8 preços encontrados`."""
    estimativa = resultado.estimativa
    selecionadas = len(estimativa.cesta.selecionadas) if estimativa else 0
    if estimativa is not None and estimativa.concluida:
        marca, texto = "✓", (
            f"{resultado.encontradas} referência(s), {selecionadas} na cesta")
    else:
        marca, texto = "!", (
            f"{resultado.encontradas} referência(s), "
            f"{selecionadas} defensável(is) — insuficiente")
    if resultado.ocorrencias:
        texto += f" · {resultado.ocorrencias[0]}"
    return f"Item {resultado.numero:02d}  {marca}  {texto}"


def estado_apos_lote(itens: list[dict]) -> EstadoPesquisa:
    """
    Para onde a pesquisa vai depois da rodada.

    Enquanto houver item na fila ela continua `EXECUTANDO`; quando a fila
    esvazia, o estado é o que os itens disserem — e nunca o que alguém
    digitou.
    """
    return estado_derivado([EstadoItem(str(i.get("estado")
                                           or EstadoItem.PENDENTE.value))
                            for i in itens])
