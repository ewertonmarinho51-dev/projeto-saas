"""
Relatórios da pesquisa de preços (§31, §32, §34).

O relatório completo é a **memória do ato**: é o que um auditor lê meses
depois para decidir se o preço estimado se sustenta. Por isso ele tem
duas propriedades que governam este módulo inteiro:

**1. Ele contém o que foi descartado.** O §31 pede, em itens separados,
"todas as referências selecionadas" (13) e "referências desconsideradas
e motivo" (14). Um relatório que mostrasse só a cesta seria uma defesa,
não uma memória — e a pergunta que a auditoria faz é justamente por que
os outros preços não entraram.

**2. Ele não inventa.** Onde o dado não existe, o relatório escreve que
não existe. "(não informado)" é informação; um campo em branco é dúvida
sobre se ninguém preencheu ou se o sistema perdeu.

O formato de saída é **Markdown**, e isso é uma decisão de arquitetura: o
§33 proíbe um segundo pipeline de PDF, e o projeto já tem
`export.gerar_pdf(titulo, markdown, branding)` — DOCX estilizado →
LibreOffice → PDF, com as larguras de tabela e o gate de geometria já
provados. Este módulo produz o conteúdo; a conversão é do motor que já
existe.

Nada aqui toca banco, sessão ou rede.
"""

from __future__ import annotations

import hashlib
import io
import json
from datetime import date, datetime, timezone
from decimal import Decimal, InvalidOperation

from . import cesta as cesta_mod
from .estados import EstadoItem
from .estatistica import REGRAS_MEDIA_PADRAO, brl, pct
from .fontes import NOME_DA_FONTE, ROTULO_DESFECHO
from .modelo import ROTULO_NATUREZA, NaturezaValor
from .perfil import enquadramento
from .perfil import obter as obter_perfil

# Versão do formato do relatório. Entra no identificador: mudar o layout
# muda o documento, e dois PDFs diferentes não podem carregar o mesmo
# identificador de versão.
#
# "2" (16/10/2026): o identificador passou a cobrir TODO o conteúdo
# decisório — quantidade, unidade, total, memória/justificativas, motivos
# e decisões do revisor (dossiê BP, tema 12b). Relatórios emitidos no
# formato "1" continuam conferíveis por `identificador_da_versao_v1`.
FORMATO = "2"

AUSENTE = "(não informado)"

_ROTULO_STATUS = {
    "selected": "selecionada",
    "candidate": "candidata",
    "rejected": "excluída",
    "warning": "sinalizada",
    "manual_review": "abaixo do piso de comparabilidade",
}


def _decimal(valor) -> Decimal | None:
    if valor in (None, ""):
        return None
    try:
        return Decimal(str(valor))
    except (InvalidOperation, ValueError, TypeError):
        return None


def _moeda(valor) -> str:
    # Decimal até o texto: o relatório é ato administrativo, e o
    # `formatar_moeda` da planilha passa por float.
    numero = _decimal(valor)
    return AUSENTE if numero is None else brl(numero)


# ---------------------------------------------------------------------------
# Neutralização de dado EXTERNO no Markdown
#
# Descrição, órgão, fornecedor e marca vêm da FONTE, não de nós. O §55 é
# explícito: todo conteúdo externo é dado não confiável.
#
# Dois caracteres bastam para transformar dado em ESTRUTURA:
#
#   * `|` acrescenta colunas à tabela. Um fornecedor que cadastre o
#     produto como "CANETA | 999999,00 | FALSO" faz o relatório oficial
#     exibir um preço que ninguém pesquisou, na coluna de preço;
#   * a quebra de linha encerra a linha da tabela e abre o que vier
#     depois. Medido: uma descrição com "\n\n## SEÇÃO FALSA" derrubou a
#     tabela de 13 colunas para 2 e injetou um cabeçalho e uma linha de
#     "VALOR GLOBAL" forjados no documento.
#
# A neutralização é de ESTRUTURA, não de conteúdo: o texto continua
# legível e integralmente presente — `|` vira `\|`, que o Markdown
# renderiza como barra, e as quebras viram espaço. Apagar o conteúdo
# esconderia o que a fonte de fato devolveu, e a evidência é o que este
# relatório existe para preservar.
# ---------------------------------------------------------------------------
def _neutralizar(valor) -> str:
    """Texto externo que pode entrar numa célula ou num título."""
    bruto = str(valor or "")
    # Quebras de linha (inclusive as de Windows e a de linha isolada)
    # viram espaço: elas encerrariam a linha da tabela ou o título.
    achatado = " ".join(bruto.replace("\r", "\n").split("\n"))
    # A barra vertical é escapada, não removida.
    return " ".join(achatado.replace("|", "\\|").split()).strip()


def _texto(valor) -> str:
    limpo = _neutralizar(valor)
    return limpo or AUSENTE


def _numero(valor) -> str:
    numero = _decimal(valor)
    if numero is None:
        return AUSENTE
    return f"{numero:g}"


def _data(valor) -> str:
    if not valor:
        return AUSENTE
    texto = str(valor)[:10]
    try:
        return date.fromisoformat(texto).strftime("%d/%m/%Y")
    except (ValueError, TypeError):
        return texto


# ---------------------------------------------------------------------------
# §34 — identificador da versão
# ---------------------------------------------------------------------------
def projecao_decisoria(pesquisa: dict, itens: list[dict],
                       referencias: dict[str, list[dict]]) -> dict:
    """
    TUDO o que decide o preço, e nada de decorativo (formato "2").

    Pesquisa: id, revisão, perfil, data-base, regras e filtros. Item:
    número, código, descrição, unidade, quantidade, estado, método,
    unitário, total, memória (com justificativas) e decisões do revisor.
    Referência: evidência (`raw_hash`), status, valor normalizado,
    unidade normalizada e motivos. Mudar qualquer um desses muda o hash.
    """
    def numero(valor):
        d = _decimal(valor)
        return None if d is None else format(d.normalize(), "f")

    projecao = {
        "formato": FORMATO,
        "pesquisa": {
            "id": str(pesquisa.get("id") or ""),
            "versao": int(pesquisa.get("versao") or 1),
            "perfil": str(pesquisa.get("perfil_normativo") or ""),
            "data_base": str(pesquisa.get("data_base") or ""),
            "regras": str(pesquisa.get("versao_regras") or ""),
            "filtros": pesquisa.get("filtros") or {},
        },
        "itens": [],
    }
    for item in sorted(itens, key=lambda i: int(i.get("numero") or 0)):
        gravado = item.get("estatisticas") or {}
        projecao["itens"].append({
            "numero": int(item.get("numero") or 0),
            "codigo": str(item.get("codigo") or ""),
            "descricao": str(item.get("descricao") or ""),
            "unidade": str(item.get("unidade") or ""),
            "quantidade": numero(item.get("quantidade")),
            "estado": str(item.get("estado") or ""),
            "metodo": str(item.get("metodo") or ""),
            "preco_estimado": numero(item.get("preco_estimado")),
            "preco_total": numero(item.get("preco_total")),
            "memoria": str(item.get("justificativa") or ""),
            "decisoes": gravado.get("decisoes") or {},
            "referencias": sorted(
                json.dumps([r.get("raw_hash") or "", r.get("status") or "",
                            numero(r.get("valor_unitario_normalizado")),
                            r.get("unidade_normalizada") or "",
                            list(r.get("motivos") or [])],
                           ensure_ascii=False, default=str)
                for r in referencias.get(str(item.get("id")), [])),
        })
    return projecao


def identificador_da_versao(pesquisa: dict, itens: list[dict],
                            referencias: dict[str, list[dict]]) -> str:
    """
    Impressão digital do RESULTADO — o item 22 do §31.

    SHA-256 da `projecao_decisoria`. O que ele permite: pegar o PDF de
    hoje, refazer a projeção meses depois e provar que é o mesmo
    resultado — ou descobrir que alguém mexeu. É por isso que ele NÃO
    inclui data de geração: dois relatórios do mesmo resultado, emitidos
    em dias diferentes, têm de bater.
    """
    canonico = json.dumps(projecao_decisoria(pesquisa, itens, referencias),
                          sort_keys=True, ensure_ascii=False,
                          separators=(",", ":"), default=str)
    return hashlib.sha256(canonico.encode("utf-8")).hexdigest()


def dados_da_emissao(pesquisa: dict, itens: list[dict],
                     referencias: dict[str, list[dict]], *, tipo: str,
                     formato: str, conteudo: bytes, nome_arquivo: str) -> dict:
    """
    O registro de UMA emissão (F140/F162): hash do conteúdo decisório
    (reprodutível, igual para o mesmo resultado), hash do ARQUIVO (prova
    do byte entregue) e a lista nominal de pendências que o documento
    imprimiu. Sem IP — dado pessoal que o registro não precisa.
    """
    decisorio = identificador_da_versao(pesquisa, itens, referencias)
    arquivo = hashlib.sha256(conteudo).hexdigest()
    perfil = obter_perfil(pesquisa.get("perfil_normativo"))
    return {
        "versao_pesquisa": int(pesquisa.get("versao") or 1),
        "tipo": tipo, "formato": formato, "formato_hash": FORMATO,
        "hash_decisorio": decisorio, "hash_arquivo": arquivo,
        "tamanho_bytes": len(conteudo), "nome_arquivo": nome_arquivo,
        "pendencias": [{"item": p["numero"], "deficiencias": p["deficiencias"]}
                       for p in pendencias_nominais(itens, referencias, perfil)],
        "idempotency_key": f"{tipo}:{formato}:{decisorio}:{arquivo}",
    }


def conferir_identificador(pesquisa: dict, itens: list[dict],
                           referencias: dict[str, list[dict]],
                           informado: str) -> str:
    """
    Conferência por terceiro, dentro do sistema: o identificador impresso
    corresponde ao resultado ATUAL desta pesquisa? Recalcula nos dois
    formatos — o v1 confere relatórios emitidos antes de 16/10/2026.
    """
    alvo = str(informado or "").strip().strip("`").lower()
    if len(alvo) < 16:
        return "informe o identificador impresso (mínimo 16 caracteres)"
    atual = identificador_da_versao(pesquisa, itens, referencias)
    if atual.startswith(alvo):
        return "confere: o documento corresponde ao resultado atual (formato 2)"
    if identificador_da_versao_v1(pesquisa, itens, referencias).startswith(alvo):
        return ("confere no formato 1 (relatório anterior a 16/10/2026): o "
                "resultado não mudou nos campos que aquele formato cobria")
    return ("NÃO confere: o resultado desta pesquisa mudou depois da "
            "emissão, ou o identificador é de outra pesquisa/revisão")


def identificador_da_versao_v1(pesquisa: dict, itens: list[dict],
                               referencias: dict[str, list[dict]]) -> str:
    """
    O identificador do formato "1", para CONFERIR relatórios emitidos
    antes de 16/10/2026. Não usar para emitir: ele não cobre quantidade,
    total, unidade nem justificativas.
    """
    projecao = {
        "formato": "1",
        "pesquisa": {
            "id": str(pesquisa.get("id") or ""),
            "versao": int(pesquisa.get("versao") or 1),
            "perfil": str(pesquisa.get("perfil_normativo") or ""),
            "data_base": str(pesquisa.get("data_base") or ""),
        },
        "itens": [],
    }
    for item in sorted(itens, key=lambda i: int(i.get("numero") or 0)):
        do_item = {
            "numero": int(item.get("numero") or 0),
            "descricao": str(item.get("descricao") or ""),
            "estado": str(item.get("estado") or ""),
            "metodo": str(item.get("metodo") or ""),
            "preco_estimado": str(item.get("preco_estimado") or ""),
            "referencias": sorted(
                (f"{r.get('raw_hash') or ''}:{r.get('status') or ''}"
                 for r in referencias.get(str(item.get("id")), [])),
            ),
        }
        projecao["itens"].append(do_item)
    canonico = json.dumps(projecao, sort_keys=True, ensure_ascii=False,
                          separators=(",", ":"), default=str)
    return hashlib.sha256(canonico.encode("utf-8")).hexdigest()


# ---------------------------------------------------------------------------
# §31 — relatório completo
# ---------------------------------------------------------------------------
def completo(pesquisa: dict, itens: list[dict],
             referencias: dict[str, list[dict]],
             *, emitido_em: datetime | None = None,
             processo: dict | None = None) -> str:
    """
    As 22 seções do §31, em Markdown, na ordem do prompt.

    A ordem não é estética: ela vai do CONTEXTO (quem, o quê, sob qual
    regra) para o MÉTODO (como se buscou, como se comparou, como se
    calculou) e só então para o RESULTADO. Um relatório que abrisse com o
    número convidaria a ler só o número.
    """
    momento = emitido_em or datetime.now(timezone.utc)
    perfil = obter_perfil(pesquisa.get("perfil_normativo"))
    concluidos = [i for i in itens
                  if str(i.get("estado")) == EstadoItem.COMPLETO.value]

    partes: list[str] = []
    ad = partes.append

    ad("# RELATÓRIO DE PESQUISA DE PREÇOS")
    ad("")
    ad("Lei nº 14.133/2021 — formação do preço estimado da contratação.")
    ad("")

    # 1–4
    ad("## 1. Identificação")
    ad("")
    ad(f"- **Pesquisa:** {_texto(pesquisa.get('nome'))}")
    ad(f"- **Identificador:** {_texto(pesquisa.get('id'))}")
    ad(f"- **Revisão:** {int(pesquisa.get('versao') or 1)}")
    if pesquisa.get("motivo_da_revisao"):
        ad(f"- **Motivo da revisão:** {_texto(pesquisa['motivo_da_revisao'])}")
    ad(f"- **Situação:** {_texto(pesquisa.get('estado'))}")
    ad(f"- **Data-base:** {_data(pesquisa.get('data_base'))}")
    ad("")

    ad("## 2. Objeto")
    ad("")
    ad(_texto(pesquisa.get("objeto")))
    ad("")

    ad("## 3. Processo")
    ad("")
    if pesquisa.get("processo_id"):
        ad(f"- **Processo vinculado:** {_texto(pesquisa.get('processo_id'))}")
        if processo:
            ad(f"- **Órgão:** {_texto(processo.get('orgao'))}")
            ad(f"- **Objeto do processo:** {_texto(processo.get('objeto'))}")
    else:
        ad("Pesquisa autônoma — ainda não vinculada a processo.")
    ad("")

    ad("## 4. Responsáveis")
    ad("")
    ad(f"- **Responsável indicado:** {_texto(pesquisa.get('responsavel'))}")
    ad(f"- **Local de referência:** {_texto(pesquisa.get('local_referencia'))}")
    ad("")

    # 5
    ad("## 5. Base normativa e perfil utilizado")
    ad("")
    ad(f"- **Perfil:** {perfil.nome}")
    ad(f"- **Base legal:** {perfil.base_legal}")
    ad(f"- **Mínimo de referências por item:** {perfil.minimo_referencias}")
    ad("- **Admite concluir com menos, mediante justificativa:** "
       + ("sim" if perfil.admite_menos_com_justificativa else "não"))
    if perfil.teto_da_mediana_em_sistema_oficial:
        ad("- **Teto da mediana:** aplicável — estimativa apoiada "
           "exclusivamente em sistema oficial de preços não supera a "
           "mediana da amostra.")
    for observacao in perfil.observacoes:
        ad(f"- {observacao}")
    ad("")

    # 6
    ad("## 6. Metodologia")
    ad("")
    ad("A pesquisa coleta referências em fontes oficiais, normaliza a "
       "unidade de fornecimento, avalia a comparabilidade de cada "
       "referência com o item da contratação, monta a cesta e forma o "
       "preço por método estatístico declarado.")
    ad("")
    ad("Nenhuma etapa preenche lacuna por estimativa: referência sem "
       "preço, sem unidade conversível ou sem comparabilidade suficiente "
       "fica fora da cesta, com o motivo registrado, e o item é "
       "declarado incompleto em vez de receber preço fabricado.")
    ad("")
    metodos = sorted({str(i.get("metodo") or "") for i in itens
                      if i.get("metodo")})
    ad(f"- **Métodos aplicados nesta pesquisa:** "
       f"{', '.join(metodos) if metodos else AUSENTE}")
    ad("- **Contagem para a regra dos três:** só as referências "
       "CONSIDERADAS no cálculo (na cesta, com preço normalizado e "
       "natureza de preço) — selecionar não basta.")
    ad("")

    # 7
    ad("## 7. Fontes consultadas")
    ad("")
    ad(_tabela_de_fontes(referencias))
    ad("")
    ad("**Trilha de consulta às fontes** — horário de coleta (UTC), "
       "desfecho de cada consulta e enquadramento da origem")
    ad("")
    ad(_trilha_de_fontes(itens, referencias, perfil))
    ad("")

    # 8
    ad("## 8. Critérios de busca")
    ad("")
    filtros = pesquisa.get("filtros") or {}
    from .execucao import janela_efetiva

    # a janela EFETIVA: uma pesquisa gravada com 365 dias consulta 180
    janela = janela_efetiva(filtros) if filtros.get("janela_dias") else None
    ad(f"- **Janela temporal:** últimos {janela} dias contados da "
       f"data-base" if janela else "- **Janela temporal:** " + AUSENTE)
    ad(f"- **Recorte geográfico:** {_texto(filtros.get('uf'))}")
    ad("- **Código de catálogo (CATMAT/CATSER):** aceito e usado quando "
       "informado; **não é exigido** — a busca por descrição opera na "
       "ausência dele.")
    ad("")

    # 9
    ad("## 9. Critérios de comparabilidade")
    ad("")
    ad("A comparabilidade de cada referência é o produto de dois juízos "
       "independentes:")
    ad("")
    ad("- **identidade** — é o mesmo produto? (código de catálogo e "
       "semelhança de descrição);")
    ad("- **circunstâncias** — a contratação é comparável? (unidade, "
       "temporalidade, quantidade, geografia e condições).")
    ad("")
    ad("A identidade **multiplica** as circunstâncias em vez de disputar "
       "peso com elas: produto diferente zera a nota por melhor que "
       "seja o resto. Cada fator é registrado separadamente, com o peso "
       "declarado, e aparece na análise item a item.")
    ad("")

    # 10
    ad("## 10. Critérios estatísticos")
    ad("")
    for linha in _criterios_estatisticos(pesquisa):
        ad(linha)
    ad("")

    # 11
    ad("## 11. Quadro-resumo")
    ad("")
    ad(quadro_resumo(itens, referencias))
    ad("")

    # 12–17
    ad("## 12. Análise item a item")
    ad("")
    # Os itens 13 a 17 do §31 são POR ITEM — referências usadas,
    # referências descartadas, memória de cálculo, unitário e total.
    # Repeti-los como seções de topo os faria aparecer uma vez só, quando
    # existe um conjunto deles para cada item. Ficam dentro de cada
    # bloco, com a correspondência dita em voz alta para quem procura a
    # numeração do prompt.
    ad("Cada item abaixo traz, na ordem: as referências consideradas no "
       "cálculo (item 13 da estrutura), as não consideradas com o motivo "
       "de cada uma (14), a memória de cálculo (15), o preço estimado "
       "unitário (16) e o valor total do item (17).")
    ad("")
    for item in sorted(itens, key=lambda i: int(i.get("numero") or 0)):
        for linha in _analise_do_item(item, referencias, perfil):
            ad(linha)

    # 18
    ad("## 18. Valor global")
    ad("")
    total = sum((_decimal(i.get("preco_total")) or Decimal("0"))
                for i in concluidos)
    ad(f"- **Itens concluídos:** {len(concluidos)} de {len(itens)}")
    ad(f"- **Valor global dos itens concluídos:** {_moeda(total)}")
    pendentes = [i for i in itens if i not in concluidos]
    if pendentes:
        numeros = ", ".join(str(int(i.get("numero") or 0))
                            for i in pendentes)
        ad(f"- **Itens não concluídos:** {numeros}. O valor global "
           "acima **não** os inclui.")
    ad("")
    nominais = pendencias_nominais(itens, referencias, perfil)
    if nominais:
        ad("**Pendências por item** — cada item que ainda não sustenta "
           "preço, com a deficiência")
        ad("")
        ad("| Item | Descrição | Situação | Considerados | Pendência |")
        ad("|---|---|---|---|---|")
        for p in nominais:
            ad(f"| {p['numero']:02d} | {_texto(p['descricao'])} "
               f"| {_texto(p['situacao'])} | {p['consideradas']} "
               f"| {_texto('; '.join(p['deficiencias']))} |")
        ad("")

    # 19
    ad("## 19. Alertas e ressalvas")
    ad("")
    for linha in _alertas(itens, referencias, perfil):
        ad(linha)
    ad("")

    # 20
    ad("## 20. Evidências e anexos")
    ad("")
    ad("Cada referência listada guarda, no banco desta pesquisa, o "
       "identificador oficial da contratação de origem e a impressão "
       "digital (SHA-256) do registro exatamente como a fonte o "
       "devolveu. A memória analítica completa acompanha este relatório "
       "em planilha (XLSX).")
    ad("")
    ad("A reprodutibilidade não depende de URL viva: o conteúdo "
       "coletado está preservado, e a impressão digital permite provar "
       "que é o mesmo registro.")
    ad("")

    # 21–22
    ad("## 21. Data e hora da pesquisa")
    ad("")
    ad(f"- **Relatório emitido em:** "
       f"{momento.strftime('%d/%m/%Y às %H:%M')} (UTC)")
    ad(f"- **Pesquisa criada em:** {_data(pesquisa.get('criado_em'))}")
    inicio, fim = _janela_de_coleta(referencias)
    if inicio:
        ad(f"- **Pesquisa realizada entre:** {inicio} e {fim} (UTC), da "
           "primeira à última coleta registrada")
    if pesquisa.get("aplicada_em"):
        ad(f"- **Aplicada ao processo em:** "
           f"{_data(pesquisa.get('aplicada_em'))}")
    ad("")

    ad("## 22. Identificador da versão")
    ad("")
    identificador = identificador_da_versao(pesquisa, itens, referencias)
    ad(f"`{identificador}`")
    ad("")
    ad(f"Impressão digital SHA-256 (formato {FORMATO}) de todo o conteúdo "
       "decisório: cabeçalho e regras da pesquisa; de cada item a "
       "descrição, a unidade, a quantidade, o método, o unitário, o total, "
       "a memória de cálculo e as decisões do revisor; de cada referência "
       "a evidência, a situação, o valor normalizado e os motivos. Não "
       "inclui a data de emissão: dois relatórios do mesmo resultado, "
       "emitidos em dias diferentes, produzem o mesmo identificador.")
    ad("")
    return "\n".join(partes)


# ---------------------------------------------------------------------------
# Metodologia escrita pela REGRA da pesquisa (dossiê BP, tema 5c)
# ---------------------------------------------------------------------------
def _criterios_estatisticos(pesquisa: dict) -> list[str]:
    from .estatistica import criterio_percentual_da

    saida = []
    if str(pesquisa.get("versao_regras") or "") == REGRAS_MEDIA_PADRAO:
        saida.append(
            "- **Método padrão:** média aritmética simples dos preços "
            "unitários considerados. Mediana, desvio-padrão amostral e "
            "coeficiente de variação entram como diagnóstico; com "
            "coeficiente acima de 25% o valor fica provisório até a "
            "análise crítica do revisor. O revisor pode definir outro "
            "método admitido pelo perfil, com justificativa registrada no "
            "item;")
    else:
        saida.append(
            "- **Método automático (regra anterior a 15/10/2026, mantida "
            "nas pesquisas criadas sob ela):** mediana quando a série é "
            "dispersa (coeficiente de variação acima de 0,25) e média "
            "quando é homogênea;")
    saida.append(
        "- **Sinalização de discrepantes:** intervalo interquartil "
        "(Tukey, fator 1,5) e desvio absoluto mediano (fator 3), a partir "
        "de 4 preços;")
    criterio = criterio_percentual_da(pesquisa.get("filtros"))
    if criterio:
        saida.append(
            f"- **Critério percentual desta cotação:** sinaliza preço acima "
            f"de {criterio[0]}% da média dos demais (elevado) ou abaixo de "
            f"{criterio[1]}% da média dos demais sem os elevados "
            "(inexequível); parâmetro da cotação, não limite legal;")
    saida.append(
        "- **Sinalização NÃO exclui.** A exclusão é ato do revisor, com "
        "motivo registrado, e a referência excluída continua neste "
        "relatório.")
    return saida


# ---------------------------------------------------------------------------
# Trilha de fontes e pendências nominais (dossiê BP, temas 6 e 7)
# ---------------------------------------------------------------------------
def _instante(valor) -> datetime | None:
    if not valor:
        return None
    try:
        momento = datetime.fromisoformat(str(valor).replace("Z", "+00:00"))
    except ValueError:
        return None
    if momento.tzinfo is None:
        momento = momento.replace(tzinfo=timezone.utc)
    return momento.astimezone(timezone.utc)


def _hora(momento: datetime | None) -> str:
    return momento.strftime("%d/%m/%Y %H:%M") if momento else AUSENTE


def _janela_de_coleta(referencias: dict[str, list[dict]]) -> tuple[str, str]:
    instantes = [m for lista in referencias.values() for linha in lista
                 if (m := _instante(linha.get("coletado_em")))]
    if not instantes:
        return "", ""
    return _hora(min(instantes)), _hora(max(instantes))


def _trilha_de_fontes(itens: list[dict], referencias: dict[str, list[dict]],
                      perfil) -> str:
    """Uma linha por fonte: coleta, desfechos (inclusive falhas) e inciso."""
    fontes: dict[str, dict] = {}
    for lista in referencias.values():
        for linha in lista:
            fid = str(linha.get("fonte_id") or "")
            info = fontes.setdefault(fid, {
                "nome": linha.get("fonte_nome") or NOME_DA_FONTE.get(fid, fid),
                "tipo": linha.get("fonte_tipo"), "coletas": [],
                "refs": 0, "consideradas": 0, "desfechos": {}})
            info["refs"] += 1
            if (m := _instante(linha.get("coletado_em"))):
                info["coletas"].append(m)
        for linha in cesta_mod.consideradas(lista):
            fontes[str(linha.get("fonte_id") or "")]["consideradas"] += 1
    for item in itens:
        for fid, desfecho in (item.get("desfechos") or {}).items():
            info = fontes.setdefault(str(fid), {
                "nome": NOME_DA_FONTE.get(str(fid), str(fid)), "tipo": None,
                "coletas": [], "refs": 0, "consideradas": 0, "desfechos": {}})
            rotulo = ROTULO_DESFECHO.get(str(desfecho), str(desfecho))
            info["desfechos"][rotulo] = info["desfechos"].get(rotulo, 0) + 1
    if not fontes:
        return "Nenhuma fonte consultada."
    saida = ["| Fonte | Enquadramento | Referências | Consideradas | "
             "Primeira coleta | Última coleta | Desfechos por item |",
             "|---|---|---|---|---|---|---|"]
    for fid, info in sorted(fontes.items(), key=lambda par: str(par[1]["nome"])):
        coletas = info["coletas"]
        desfechos = "; ".join(f"{rotulo}: {n}" for rotulo, n
                              in sorted(info["desfechos"].items())) or AUSENTE
        saida.append(
            f"| {_texto(info['nome'])} "
            f"| {enquadramento(fid, info['tipo'], perfil)} "
            f"| {info['refs']} | {info['consideradas']} "
            f"| {_hora(min(coletas)) if coletas else AUSENTE} "
            f"| {_hora(max(coletas)) if coletas else AUSENTE} "
            f"| {_texto(desfechos)} |")
    return "\n".join(saida)


ROTULO_ESTADO_ITEM = {
    EstadoItem.PENDENTE.value: "não pesquisado",
    EstadoItem.BUSCANDO.value: "pesquisa em curso",
    EstadoItem.CLASSIFICANDO.value: "pesquisa em curso",
    EstadoItem.EM_REVISAO.value: "aguardando revisão",
    EstadoItem.COMPLETO.value: "concluído",
    EstadoItem.INCOMPLETO.value: "sem preços suficientes",
    EstadoItem.ERRO.value: "falha técnica na consulta",
}


def pendencias_nominais(itens: list[dict], referencias: dict[str, list[dict]],
                        perfil=None) -> list[dict]:
    """
    Cada item NÃO concluído — ou concluído com ressalva — com a
    deficiência dita por extenso. É a lista que a tela mostra ANTES de
    emitir e que o documento imprime (o BP avisava "não atende" sem dizer
    quais itens, J12b).
    """
    perfil = perfil or obter_perfil(None)
    saida = []
    for item in sorted(itens, key=lambda i: int(i.get("numero") or 0)):
        estado = str(item.get("estado") or EstadoItem.PENDENTE.value)
        linhas = referencias.get(str(item.get("id")), [])
        n = len(cesta_mod.consideradas(linhas))
        gravado = item.get("estatisticas") or {}
        decisoes = gravado.get("decisoes") or {}
        deficiencias: list[str] = []
        if estado == EstadoItem.ERRO.value:
            deficiencias.append("as fontes de preço não responderam — "
                                "repetir a consulta")
        elif estado in (EstadoItem.PENDENTE.value, EstadoItem.BUSCANDO.value,
                        EstadoItem.CLASSIFICANDO.value):
            deficiencias.append("ainda não pesquisado")
        if estado != EstadoItem.COMPLETO.value and n < perfil.minimo_referencias \
                and estado not in (EstadoItem.ERRO.value, EstadoItem.PENDENTE.value):
            if decisoes.get("excecao"):
                deficiencias.append(
                    f"{n}/{perfil.minimo_referencias} considerados, com "
                    "exceção registrada — aguarda conclusão do revisor")
            else:
                deficiencias.append(
                    f"{n}/{perfil.minimo_referencias} preços considerados "
                    "e sem justificativa de exceção")
        if estado == EstadoItem.EM_REVISAO.value:
            deficiencias.append("preço não confirmado pelo revisor")
        for pendencia in gravado.get("pendencias") or []:
            if estado != EstadoItem.COMPLETO.value:
                deficiencias.append(f"análise crítica: {pendencia}")
        if estado == EstadoItem.COMPLETO.value and decisoes.get("excecao"):
            deficiencias.append(
                f"concluído com {n} preço(s) mediante exceção "
                f"({decisoes['excecao'].get('base_normativa') or 'perfil'})")
        if deficiencias:
            saida.append({"item_id": str(item.get("id")),
                          "numero": int(item.get("numero") or 0),
                          "descricao": str(item.get("descricao") or ""),
                          "situacao": ROTULO_ESTADO_ITEM.get(estado, estado),
                          "consideradas": n, "deficiencias": deficiencias,
                          "impede": estado != EstadoItem.COMPLETO.value})
    return saida


def _tabela_de_fontes(referencias: dict[str, list[dict]]) -> str:
    """§31.7 — quais fontes entraram, e com quantas referências."""
    contagem: dict[tuple[str, str], int] = {}
    for lista in referencias.values():
        for linha in lista:
            chave = (str(linha.get("fonte_nome") or linha.get("fonte_id")
                         or AUSENTE),
                     str(linha.get("fonte_tipo") or ""))
            contagem[chave] = contagem.get(chave, 0) + 1
    if not contagem:
        return "Nenhuma referência coletada."
    linhas = ["| Fonte | Natureza | Referências |", "|---|---|---|"]
    for (nome, tipo), quantas in sorted(contagem.items()):
        linhas.append(f"| {nome} | {tipo or AUSENTE} | {quantas} |")
    return "\n".join(linhas)


def quadro_resumo(itens: list[dict],
                  referencias: dict[str, list[dict]] | None = None) -> str:
    """§31.11 — uma linha por item, com o essencial e a SITUAÇÃO."""
    if not itens:
        return "Nenhum item nesta pesquisa."
    referencias = referencias or {}
    linhas = [
        "| Item | Descrição | Unid. | Qtd. | Método | Considerados | "
        "Unitário | Total | Situação |",
        "|---|---|---|---|---|---|---|---|---|",
    ]
    for item in sorted(itens, key=lambda i: int(i.get("numero") or 0)):
        considerados = _considerados_do_item(item, referencias)
        estado = str(item.get("estado") or "")
        linhas.append(
            f"| {int(item.get('numero') or 0):02d} "
            f"| {_texto(item.get('descricao'))} "
            f"| {_texto(item.get('unidade'))} "
            f"| {_numero(item.get('quantidade'))} "
            f"| {_texto(item.get('metodo'))} "
            f"| {considerados if considerados is not None else AUSENTE} "
            f"| {_moeda(item.get('preco_estimado'))} "
            f"| {_moeda(item.get('preco_total'))} "
            f"| {ROTULO_ESTADO_ITEM.get(estado, _texto(estado))} |")
    return "\n".join(linhas)


def _considerados_do_item(item: dict,
                          referencias: dict[str, list[dict]]) -> int | None:
    """Pelas linhas, quando vieram; senão pelo que o item gravou."""
    lista = referencias.get(str(item.get("id")))
    if lista is not None:
        return len(cesta_mod.consideradas(lista))
    return cesta_mod.na_cesta_do_item(item)


def _analise_do_item(item: dict, referencias: dict[str, list[dict]],
                     perfil=None) -> list[str]:
    """
    §31.12 a 17 para um item: referências CONSIDERADAS, não consideradas
    com motivo, memória de cálculo, decisões do revisor, pendências,
    unitário e total.
    """
    perfil = perfil or obter_perfil(None)
    numero = int(item.get("numero") or 0)
    lista = referencias.get(str(item.get("id")), [])
    consideradas = cesta_mod.consideradas(lista)
    fora = cesta_mod.desconsideradas(lista)
    estado = str(item.get("estado") or "")

    saida = [f"### Item {numero:02d} — {_texto(item.get('descricao'))}", ""]
    saida.append(f"- **Unidade:** {_texto(item.get('unidade'))}")
    saida.append(f"- **Quantidade:** {_numero(item.get('quantidade'))}")
    if item.get("codigo"):
        saida.append(f"- **Catálogo:** {_texto(item.get('tipo_catalogo'))} "
                     f"{_texto(item.get('codigo'))}")
    else:
        saida.append("- **Catálogo:** não informado — a busca foi feita por "
                     "descrição")
    saida.append(f"- **Situação:** {ROTULO_ESTADO_ITEM.get(estado, _texto(estado))}"
                 f" — {len(consideradas)}/{perfil.minimo_referencias} preços "
                 "considerados no cálculo")
    saida.append("")

    memoria = item.get("estatisticas") or {}
    estatisticas = memoria.get("estatisticas") or {}
    if estatisticas:
        saida.append("**Estatística da cesta**")
        saida.append("")
        saida.append("| Considerados | Menor | Média | Mediana | Maior | "
                     "Desvio-padrão | CV |")
        saida.append("|---|---|---|---|---|---|---|")
        cv = _decimal(estatisticas.get("coeficiente_variacao"))
        saida.append(
            f"| {estatisticas.get('quantidade', 0)} "
            f"| {_moeda(estatisticas.get('menor'))} "
            f"| {_moeda(estatisticas.get('media'))} "
            f"| {_moeda(estatisticas.get('mediana'))} "
            f"| {_moeda(estatisticas.get('maior'))} "
            f"| {_moeda(estatisticas.get('desvio_padrao'))} "
            f"| {pct(cv) if cv is not None else AUSENTE} |")
        saida.append("")

    saida.append(f"**Referências consideradas no cálculo "
                 f"({len(consideradas)})** — §31.13")
    saida.append("")
    saida.append(_tabela_de_referencias(consideradas, perfil=perfil,
                                        com_motivo=any(
                                            str(r.get("status")) == "warning"
                                            for r in consideradas)))
    saida.append("")
    links = _links_de_verificacao(consideradas)
    if links:
        saida.append("Verificação na fonte oficial: " + "; ".join(links))
        saida.append("")
    cotacoes = _cotacoes_diretas(lista)
    if cotacoes:
        saida.append(cotacoes)
        saida.append("")

    # §31.14 — o que ficou de fora NUNCA some do relatório.
    saida.append(f"**Referências não consideradas ({len(fora)})** — §31.14")
    saida.append("")
    if fora:
        saida.append(_tabela_de_referencias(fora, perfil=perfil,
                                            com_motivo=True))
        if any(str(r.get("status")) == "rejected" for r in fora) and \
                perfil.fundamento_desconsideracao:
            saida.append("")
            saida.append("Referências excluídas pelo revisor, com o motivo "
                         "registrado, conforme "
                         f"{perfil.fundamento_desconsideracao}.")
    else:
        saida.append("Nenhuma referência ficou fora do cálculo neste item.")
    saida.append("")

    saida.append("**Memória de cálculo** — §31.15")
    saida.append("")
    justificativa = str(item.get("justificativa") or "").strip()
    if justificativa:
        for linha in justificativa.splitlines():
            if linha.strip():
                saida.append(f"- {_neutralizar(linha)}")
    else:
        saida.append(f"- {AUSENTE}")
    saida.append("")

    decisoes = memoria.get("decisoes") or {}
    excecao = decisoes.get("excecao")
    if excecao:
        saida.append("**Exceção à regra dos três**")
        saida.append("")
        saida.append(f"- **Fundamento:** {_texto(excecao.get('fundamento_texto'))}"
                     f" — {_texto(excecao.get('base_normativa'))}")
        saida.append(f"- **Justificativa do gestor:** {_texto(excecao.get('texto'))}")
        saida.append(f"- **Aprovação:** {_texto(excecao.get('aprovador'))} "
                     "(declarada como juntada aos autos)")
        saida.append(f"- **Preços considerados na exceção:** "
                     f"{excecao.get('consideradas')}")
        saida.append("")
    for anterior in decisoes.get("excecoes_anteriores") or []:
        if anterior.get("motivo_invalidacao"):
            saida.append(f"- Exceção anterior invalidada: "
                         f"{_texto(anterior.get('motivo_invalidacao'))}.")
    metodo = decisoes.get("metodo")
    if metodo:
        saida.append(f"- **Método definido pelo revisor:** "
                     f"{_texto(metodo.get('metodo'))} — "
                     f"{_texto(metodo.get('justificativa'))}")
        saida.append("")

    pendencias = memoria.get("pendencias") or []
    if pendencias:
        saida.append("**Pendências de análise crítica**")
        saida.append("")
        for pendencia in pendencias:
            saida.append(f"- {_texto(pendencia)}")
        saida.append("")

    anomalias = memoria.get("anomalias") or []
    if anomalias:
        saida.append("**Candidatos discrepantes sinalizados**")
        saida.append("")
        for anomalia in anomalias:
            saida.append(
                f"- {_moeda(anomalia.get('valor'))} — "
                f"{_texto(anomalia.get('motivo'))} "
                f"(critério {_texto(anomalia.get('criterio'))}). "
                "Sinalizado para revisão; não excluído automaticamente.")
        saida.append("")
    marcas = [m for m in memoria.get("marcas_percentuais") or []
              if m.get("marca") != "valido"]
    if marcas:
        saida.append("**Sinalizações do critério percentual da cotação**")
        saida.append("")
        for marca in marcas:
            rotulo = ("elevado" if marca.get("marca") == "elevado_sinalizado"
                      else "inexequível")
            saida.append(
                f"- {_moeda(marca.get('valor'))} = "
                f"{_texto(str(marca.get('percentual')).replace('.', ','))}% da "
                f"média dos demais ({_moeda(marca.get('base'))}) — "
                f"sinalizado como {rotulo}; não excluído automaticamente.")
        saida.append("")

    saida.append(f"- **Preço estimado unitário (§31.16):** "
                 f"{_moeda(item.get('preco_estimado'))}")
    saida.append(f"- **Valor total do item (§31.17):** "
                 f"{_moeda(item.get('preco_total'))}")
    saida.append("")
    return saida


def _links_de_verificacao(linhas: list[dict]) -> list[str]:
    from . import compras_gov
    from . import pncp as pncp_mod

    links = []
    for linha in linhas:
        bruto = linha.get("bruto") or {}
        fid = str(linha.get("fonte_id") or "")
        url = (pncp_mod.url_de_verificacao(bruto) if fid == "pncp"
               else compras_gov.url_de_verificacao(bruto)
               if fid.startswith("compras_gov") else None)
        if url:
            links.append(f"[{_texto(linha.get('id_externo'))}]({url})")
    return links


def _cotacoes_diretas(linhas: list[dict]) -> str:
    """
    A trilha do art. 23, § 1º, IV, para cada cotação direta do item:
    fornecedor, CNPJ, data, solicitação formal, justificativa da escolha
    e a impressão digital do comprovante juntado aos autos.
    """
    cotacoes = [linha for linha in linhas
                if str(linha.get("fonte_id")) == "cotacao_direta"]
    if not cotacoes:
        return ""
    saida = [f"**Cotações diretas com fornecedores ({len(cotacoes)})** — "
             "Lei 14.133/2021, art. 23, § 1º, IV", "",
             "| Fornecedor | CNPJ | Data | Unitário | Solicitação formal | "
             "Justificativa | Comprovante (SHA-256) |",
             "|---|---|---|---|---|---|---|"]
    for linha in cotacoes:
        bruto = linha.get("bruto") or {}
        comprovante = bruto.get("comprovante") or {}
        saida.append("| " + " | ".join([
            _texto(linha.get("fornecedor")),
            _texto(linha.get("ni_fornecedor")),
            _data(linha.get("data_compra")),
            _moeda(linha.get("valor_unitario_original")),
            _texto(bruto.get("solicitacao_formal")),
            _texto(bruto.get("justificativa_escolha")),
            _texto(comprovante.get("sha256")),
        ]) + " |")
    return "\n".join(saida)


def _tabela_de_referencias(linhas: list[dict], *, perfil=None,
                           com_motivo: bool = False) -> str:
    if not linhas:
        return "Nenhuma."
    # "Natureza" é COLUNA, não nota de rodapé. A diferença entre um
    # preço que alguém pagou e um valor que outro órgão apenas esperava
    # pagar é a primeira coisa que um auditor pergunta sobre uma
    # referência — não pode depender de o leitor abrir o campo de
    # motivos. "Inc." é o inciso de origem (ver §7 e `perfil.enquadramento`).
    from .perfil import inciso_da_fonte

    cabecalho = ("| Fonte | Inc. | Natureza | Órgão | UF | Data | Qtd. | "
                 "Unid. | Unitário | Compat. |")
    separador = "|---|---|---|---|---|---|---|---|---|---|"
    if com_motivo:
        cabecalho = cabecalho[:-1] + " Situação e motivo |"
        separador += "---|"
    dentro = {id(linha) for linha in cesta_mod.consideradas(linhas)}
    saida = [cabecalho, separador]
    for linha in linhas:
        score = _decimal(linha.get("score"))
        compat = f"{score:.0%}" if score is not None else AUSENTE
        celulas = [
            _texto(linha.get("fonte_nome") or linha.get("fonte_id")),
            inciso_da_fonte(linha.get("fonte_id"), linha.get("fonte_tipo"))
            or "—",
            _texto(linha.get("rotulo_natureza")
                   or ROTULO_NATUREZA.get(
                       NaturezaValor(str(linha.get("natureza_valor")
                                         or "outro")), "")),
            _texto(linha.get("orgao")),
            _texto(linha.get("uf")),
            _data(linha.get("data_resultado") or linha.get("data_compra")),
            _numero(linha.get("quantidade_original")),
            _texto(linha.get("unidade_normalizada")
                   or linha.get("unidade_original")),
            _moeda(linha.get("valor_unitario_normalizado")
                   or linha.get("valor_unitario_original")),
            compat,
        ]
        if com_motivo:
            status = str(linha.get("status") or "")
            if id(linha) in dentro:
                rotulo = ("considerada — sinalizada para revisão"
                          if status == "warning" else "considerada")
            elif status in cesta_mod.NA_CESTA:
                rotulo = "marcada, mas fora do cálculo"
            else:
                rotulo = _ROTULO_STATUS.get(status, status)
            motivos = "; ".join(str(m) for m in (linha.get("motivos") or []))
            celulas.append(_texto(rotulo + (f" — {motivos}" if motivos else "")))
        saida.append("| " + " | ".join(celulas) + " |")
    return "\n".join(saida)


def _alertas(itens: list[dict], referencias: dict[str, list[dict]],
             perfil) -> list[str]:
    """
    §31.19 — o que o leitor precisa saber antes de usar este preço.

    Escrito em linguagem de RESSALVA, nunca de conclusão jurídica: uma
    fórmula estatística sinaliza dispersão, não ilegalidade.
    """
    saida: list[str] = []
    incompletos = [i for i in itens
                   if str(i.get("estado")) == EstadoItem.INCOMPLETO.value]
    se_erro = [i for i in itens
               if str(i.get("estado")) == EstadoItem.ERRO.value]
    por_revisar = [i for i in itens
                   if str(i.get("estado")) == EstadoItem.EM_REVISAO.value]

    if incompletos:
        numeros = ", ".join(str(int(i.get("numero") or 0))
                            for i in incompletos)
        saida.append(
            f"- **Itens sem preço formado ({len(incompletos)}):** {numeros}. "
            f"A amostra não alcançou o mínimo de {perfil.minimo_referencias} "
            "referências defensáveis exigido pelo perfil, e nenhum preço "
            "foi fabricado para completar a cesta.")
    if por_revisar:
        saida.append(
            f"- **Itens ainda em revisão ({len(por_revisar)}):** o preço "
            "calculado não passou por confirmação humana.")
    if se_erro:
        saida.append(
            f"- **Itens com falha técnica ({len(se_erro)}):** a consulta às "
            "fontes não se completou; a pesquisa desses itens precisa ser "
            "repetida.")

    discrepantes = 0
    manuais = 0
    for item in itens:
        memoria = item.get("estatisticas") or {}
        discrepantes += len(memoria.get("anomalias") or [])
    for lista in referencias.values():
        manuais += sum(1 for r in lista
                       if str(r.get("status")) == "manual_review")
    if discrepantes:
        saida.append(
            f"- **Candidatos discrepantes sinalizados ({discrepantes}):** "
            "valores distantes da mediana da própria amostra. A "
            "sinalização é estatística e pede revisão — não afirma "
            "inexequibilidade nem irregularidade.")
    if manuais:
        saida.append(
            f"- **Referências abaixo do piso de comparabilidade "
            f"({manuais}):** não entraram na cesta automaticamente e "
            "permanecem disponíveis para inclusão manual justificada.")

    ocorrencias: list[str] = []
    for item in itens:
        for ocorrencia in (item.get("ocorrencias") or []):
            if ocorrencia not in ocorrencias:
                ocorrencias.append(str(ocorrencia))
    for ocorrencia in ocorrencias[:10]:
        saida.append(f"- **Ocorrência de fonte:** {ocorrencia}")

    if not saida:
        saida.append("- Nenhuma ressalva registrada nesta pesquisa.")
    return saida


# ---------------------------------------------------------------------------
# §32 — relatório resumido
# ---------------------------------------------------------------------------
PRECOS_EM_DESTAQUE = 3

# No QUADRO compacto a ausência vira travessão, e não "(não informado)".
# Não é inconsistência com o resto do módulo: numa tabela de 210 linhas o
# texto longo repetido em três colunas alarga a tabela até estourar a
# largura útil da página — o defeito de geometria que a Fase 2.1 gastou
# um ciclo inteiro para fechar. Na PROSA e no relatório completo, onde
# não há esse custo, a ausência continua escrita por extenso.
VAZIO_NO_QUADRO = "—" 


def resumido(pesquisa: dict, itens: list[dict],
             referencias: dict[str, list[dict]],
             *, emitido_em: datetime | None = None) -> str:
    """
    A versão compacta do §32: uma linha por item, com os três primeiros
    preços da cesta em destaque e o restante contado.

    Três não é número mágico — é a regra dos três preços da própria Lei,
    e mostrá-los explicitamente é o que permite conferir o cálculo de
    cabeça.
    """
    momento = emitido_em or datetime.now(timezone.utc)
    perfil = obter_perfil(pesquisa.get("perfil_normativo"))
    partes: list[str] = []
    ad = partes.append

    ad("# PESQUISA DE PREÇOS — QUADRO RESUMIDO")
    ad("")
    ad(f"**{_texto(pesquisa.get('nome'))}** · revisão "
       f"{int(pesquisa.get('versao') or 1)} · data-base "
       f"{_data(pesquisa.get('data_base'))}")
    ad("")

    # 12 colunas, como antes (a largura útil da página é o limite medido
    # na Fase 2.1): "Outras" virou a contagem de CONSIDERADOS (N/3) e a
    # "Mediana", que é diagnóstico, cedeu lugar à SITUAÇÃO do item — o BP
    # imprimia item pendente igual a item regular (dossiê, tema 6e).
    cabecalho = ["Item", "Descrição", "Qtd."]
    cabecalho += [f"Preço {n}" for n in range(1, PRECOS_EM_DESTAQUE + 1)]
    cabecalho += ["Cons.", "Média", "Situação", "Método", "Unitário", "Total"]
    ad("| " + " | ".join(cabecalho) + " |")
    ad("|" + "---|" * len(cabecalho))

    for item in sorted(itens, key=lambda i: int(i.get("numero") or 0)):
        lista = cesta_mod.consideradas(
            referencias.get(str(item.get("id")), []))
        valores = sorted(v for v in (
            _decimal(r.get("valor_unitario_normalizado")) for r in lista)
            if v is not None)
        destaque = [_compacto(v) for v in valores[:PRECOS_EM_DESTAQUE]]
        destaque += [VAZIO_NO_QUADRO] * (PRECOS_EM_DESTAQUE - len(destaque))
        if len(valores) > PRECOS_EM_DESTAQUE:
            destaque[-1] += f" (+{len(valores) - PRECOS_EM_DESTAQUE})"

        memoria = (item.get("estatisticas") or {}).get("estatisticas") or {}
        estado = str(item.get("estado") or "")
        celulas = [
            f"{int(item.get('numero') or 0):02d}",
            _texto(item.get("descricao")),
            _numero(item.get("quantidade")),
            *destaque,
            f"{len(valores)}/{perfil.minimo_referencias}",
            _compacto(memoria.get("media")),
            ROTULO_ESTADO_ITEM.get(estado, _texto(estado)),
            str(item.get("metodo") or VAZIO_NO_QUADRO),
            _compacto(item.get("preco_estimado")),
            _compacto(item.get("preco_total")),
        ]
        ad("| " + " | ".join(celulas) + " |")
    ad("")

    nominais = pendencias_nominais(itens, referencias, perfil)
    if nominais:
        ad("**Pendências e ressalvas por item**")
        ad("")
        for p in nominais:
            ad(f"- Item {p['numero']:02d} ({_texto(p['situacao'])}): "
               f"{_texto('; '.join(p['deficiencias']))}")
        ad("")

    concluidos = [i for i in itens
                  if str(i.get("estado")) == EstadoItem.COMPLETO.value]
    total = sum((_decimal(i.get("preco_total")) or Decimal("0"))
                for i in concluidos)
    ad(f"**Valor global {_plural_concluidos(len(concluidos))}: "
       f"{_moeda(total)}**")
    ad("")

    ad("## Metodologia e fontes")
    ad("")
    ad(f"- **Perfil normativo:** {perfil.nome} ({perfil.base_legal})")
    ad("- **Formação do preço:** por comparabilidade e prioridade "
       "normativa da fonte, nunca por menor preço. Item sem amostra "
       "defensável fica incompleto — nenhum preço é fabricado.")
    ad(_tabela_de_fontes(referencias))
    ad("")
    ad(f"Emitido em {momento.strftime('%d/%m/%Y às %H:%M')} (UTC). "
       f"Identificador da versão: "
       f"`{identificador_da_versao(pesquisa, itens, referencias)[:16]}…`")
    ad("")
    ad("Este quadro é um resumo. A memória de cálculo, as referências "
       "desconsideradas e os motivos de cada exclusão estão no relatório "
       "completo.")
    return "\n".join(partes)


# ---------------------------------------------------------------------------
# §33 — memória analítica em XLSX
# ---------------------------------------------------------------------------
_INICIO_DE_FORMULA = ("=", "+", "-", "@", "\t", "\r")


def _linha_segura(celulas: list) -> list:
    """
    Texto que a planilha leria como FÓRMULA vira texto literal (SEC-03).

    O openpyxl grava como fórmula qualquer string que comece com "=";
    descrição, órgão e fornecedor vêm da fonte ou do servidor (cotação
    direta), e um "=HYPERLINK(...)" ali executaria ao abrir o arquivo. O
    apóstrofo inicial é a marca de texto do próprio Excel. Números são
    gravados como números e não passam por aqui.
    """
    return ["'" + c if isinstance(c, str) and c.startswith(_INICIO_DE_FORMULA)
            else c for c in celulas]


def xlsx_analitico(pesquisa: dict, itens: list[dict],
                   referencias: dict[str, list[dict]]) -> bytes:
    """
    A planilha da memória analítica: uma aba de itens e uma de
    referências, **incluindo as desconsideradas**.

    É aqui que a pesquisa de 210 itens fica manejável: 6.300 linhas numa
    aba se filtram e se somam; as mesmas 6.300 num PDF ninguém confere.
    O relatório completo continua trazendo tudo — a planilha não o
    substitui, dá outro jeito de ler o mesmo conteúdo.
    """
    from openpyxl import Workbook

    from .perfil import inciso_da_fonte

    wb = Workbook()

    aba = wb.active
    aba.title = "Itens"
    aba.append(["Item", "Código", "Catálogo", "Descrição", "Unidade",
                "Quantidade", "Situação", "Método", "Preço unitário",
                "Valor total", "Referências", "Consideradas no cálculo",
                "Pendências"])
    pendentes = {p["item_id"]: "; ".join(p["deficiencias"]) for p in
                 pendencias_nominais(itens, referencias,
                                     obter_perfil(pesquisa.get("perfil_normativo")))}
    for item in sorted(itens, key=lambda i: int(i.get("numero") or 0)):
        lista = referencias.get(str(item.get("id")), [])
        aba.append(_linha_segura([
            int(item.get("numero") or 0),
            str(item.get("codigo") or ""),
            str(item.get("tipo_catalogo") or ""),
            str(item.get("descricao") or ""),
            str(item.get("unidade") or ""),
            _float(item.get("quantidade")),
            str(item.get("estado") or ""),
            str(item.get("metodo") or ""),
            _float(item.get("preco_estimado")),
            _float(item.get("preco_total")),
            len(lista),
            # a MESMA contagem do cálculo, do relatório e da tela
            len(cesta_mod.consideradas(lista)),
            pendentes.get(str(item.get("id")), ""),
        ]))
    for coluna, largura in zip("ABCDEFGHIJKLM",
                              (6, 12, 10, 48, 10, 12, 12, 10, 14, 14, 12, 12,
                               60)):
        aba.column_dimensions[coluna].width = largura

    detalhe = wb.create_sheet("Referências")
    detalhe.append(["Item", "Situação", "Considerada no cálculo",
                    "Inciso de origem", "Coletado em (UTC)",
                    "Fonte", "Natureza", "Órgão", "UF",
                    "Município", "Fornecedor", "Marca", "Data",
                    "Descrição na fonte", "Unid. original", "Qtd.",
                    "Preço original", "Unid. normalizada",
                    "Preço normalizado", "Comparabilidade", "Identidade",
                    "Circunstâncias", "Identificador externo",
                    "Impressão da evidência", "Motivos"])
    for item in sorted(itens, key=lambda i: int(i.get("numero") or 0)):
        numero = int(item.get("numero") or 0)
        lista = referencias.get(str(item.get("id")), [])
        dentro = {id(r) for r in cesta_mod.consideradas(lista)}
        for linha in lista:
            detalhe.append(_linha_segura([
                numero,
                _ROTULO_STATUS.get(str(linha.get("status")),
                                   str(linha.get("status") or "")),
                "sim" if id(linha) in dentro else "não",
                inciso_da_fonte(linha.get("fonte_id"),
                                linha.get("fonte_tipo")) or "",
                _hora(_instante(linha.get("coletado_em")))
                if linha.get("coletado_em") else "",
                str(linha.get("fonte_nome") or linha.get("fonte_id") or ""),
                str(linha.get("fonte_tipo") or ""),
                str(linha.get("orgao") or ""),
                str(linha.get("uf") or ""),
                str(linha.get("municipio") or ""),
                str(linha.get("fornecedor") or ""),
                str(linha.get("marca") or ""),
                str(linha.get("data_resultado")
                    or linha.get("data_compra") or ""),
                str(linha.get("descricao_original") or ""),
                str(linha.get("unidade_original") or ""),
                _float(linha.get("quantidade_original")),
                _float(linha.get("valor_unitario_original")),
                str(linha.get("unidade_normalizada") or ""),
                _float(linha.get("valor_unitario_normalizado")),
                _float(linha.get("score")),
                _float(linha.get("identidade")),
                _float(linha.get("circunstancias")),
                str(linha.get("id_externo") or ""),
                str(linha.get("raw_hash") or ""),
                "; ".join(str(m) for m in (linha.get("motivos") or [])),
            ]))
    for coluna, largura in zip(
            ["A", "B", "C", "D", "E", "F", "G", "H", "I", "J", "K", "L",
             "M", "N"],
            (6, 22, 12, 10, 18, 22, 20, 28, 6, 18, 28, 14, 12, 48)):
        detalhe.column_dimensions[coluna].width = largura

    ficha = wb.create_sheet("Identificação")
    ficha.append(["Campo", "Valor"])
    for rotulo, valor in (
            ("Pesquisa", pesquisa.get("nome")),
            ("Identificador", pesquisa.get("id")),
            ("Revisão", pesquisa.get("versao")),
            ("Perfil normativo", pesquisa.get("perfil_normativo")),
            ("Data-base", pesquisa.get("data_base")),
            ("Situação", pesquisa.get("estado")),
            ("Identificador da versão",
             identificador_da_versao(pesquisa, itens, referencias)),
    ):
        ficha.append([rotulo, str(valor if valor is not None else "")])
    ficha.column_dimensions["A"].width = 24
    ficha.column_dimensions["B"].width = 70

    buffer = io.BytesIO()
    wb.save(buffer)
    return buffer.getvalue()


def _compacto(valor) -> str:
    """Moeda para o quadro compacto: ausência vira travessão."""
    numero = _decimal(valor)
    return (VAZIO_NO_QUADRO if numero is None
            else brl(numero))


def _plural_concluidos(quantos: int) -> str:
    """
    "de 1 item concluído" / "de 3 itens concluídos".

    Concordância importa num documento que vai para processo
    administrativo: "dos 1 item(ns)" denuncia texto gerado por máquina e
    tira credibilidade do que está certo no resto da página.
    """
    if quantos == 1:
        return "de 1 item concluído"
    return f"dos {quantos} itens concluídos"


def _float(valor) -> float | None:
    """
    `None` vira célula VAZIA, não zero.

    Zero numa planilha de preços é um preço; vazio é a ausência dele. A
    diferença muda a soma que alguém vai fazer na coluna.
    """
    numero = _decimal(valor)
    return None if numero is None else float(numero)


def nome_do_arquivo(pesquisa: dict, sufixo: str, extensao: str) -> str:
    """Nome estável e legível para os arquivos exportados."""
    bruto = str(pesquisa.get("nome") or "pesquisa").strip()
    seguro = "".join(c if c.isalnum() or c in " -_" else "-" for c in bruto)
    seguro = "-".join(seguro.split())[:60] or "pesquisa"
    versao = int(pesquisa.get("versao") or 1)
    return f"{seguro}-rev{versao}-{sufixo}.{extensao}"
