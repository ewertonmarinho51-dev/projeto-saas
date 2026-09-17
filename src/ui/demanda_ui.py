"""
Consolidar Demandas — a tela.

Posição no fluxo (§4): antes do Formulário Matriz. O servidor recebe os
Documentos de Formalização de Demanda das secretarias, confere o que o
sistema leu, resolve o que ficou em conflito e aplica ao processo. A
partir daí é a planilha orçamentária de sempre.

A tela é uma sequência de conferências, não um botão de importar. Cada
etapa mostra o que o sistema entendeu ANTES de somar, porque o número
que sai daqui vira a quantidade oficial do processo — e um erro de
consolidação atravessa o DFD, o ETP, o Termo de Referência e o edital
sem encontrar ninguém no caminho.

O que esta tela nunca faz: somar em silêncio, esconder arquivo que não
conseguiu ler, ou aplicar com conflito pendente.
"""

from __future__ import annotations

import streamlit as st

from .. import auth, db, governanca, state
from ..demanda import aplicacao, consolidacao, exportacao, ingestao
from . import components

# Chaves de sessão, prefixadas para não colidir com o formulário matriz.
ARQUIVOS = "demanda_arquivos"
ROTULOS = "demanda_rotulos"
ACEITOS = "demanda_conflitos_aceitos"

_COR_DO_STATUS = {
    consolidacao.LIDO: "green",
    consolidacao.IMAGEM: "orange",
    consolidacao.ILEGIVEL: "red",
}
_TEXTO_DO_STATUS = {
    consolidacao.LIDO: "lido",
    consolidacao.IMAGEM: "não lido — o PDF é uma imagem",
    consolidacao.ILEGIVEL: "não lido — sem quadro de itens",
}


def disponivel() -> bool:
    """Flag ligada e banco de pé. Nasce desligada, como o §34 pede."""
    return db.flag_ativa(governanca.FLAG_CONSOLIDACAO)


def render_demanda() -> None:
    components.render_page_header(
        "Consolidar Demandas",
        "Junte os pedidos das secretarias numa tabela só, com a conta "
        "de cada item conferível.",
    )

    enviados = st.file_uploader(
        "Documentos de Formalização de Demanda (PDF)",
        type=["pdf"], accept_multiple_files=True, key=ARQUIVOS,
        help="Pode mandar de várias secretarias de uma vez. "
             "Um arquivo pode conter mais de um documento.",
    )
    if not enviados:
        st.info(
            "Envie os PDFs que as secretarias mandaram. O sistema lê o "
            "órgão de dentro de cada documento — não é preciso renomear "
            "arquivo."
        )
        return

    origens = _ler(enviados)
    _render_arquivos(origens)

    consolidado = consolidacao.consolidar(origens)
    if not consolidado.linhas:
        st.warning(
            "Nenhum item foi lido. Confira a lista acima: os arquivos "
            "podem ser digitalizações, que o sistema não lê."
        )
        return

    _render_conflitos(consolidado)
    _render_tabela(consolidado)
    _render_conferencia(consolidado)
    _render_acoes(consolidado)


# ---------------------------------------------------------------------------
# Leitura
# ---------------------------------------------------------------------------
def _ler(enviados) -> list[consolidacao.Origem]:
    """
    Cada arquivo vira uma origem, com o rótulo que o servidor tiver
    corrigido. A leitura é refeita a cada rerun — é barata, e guardar
    bytes de PDF em `session_state` cresce sem teto.
    """
    rotulos = st.session_state.setdefault(ROTULOS, {})
    origens = []
    for arquivo in enviados:
        try:
            origem = ingestao.ler(arquivo.name, arquivo.getvalue(),
                                  secretaria=rotulos.get(arquivo.name, ""))
        except ingestao.ErroIngestao as erro:
            st.error(f"**{arquivo.name}** — {erro}")
            continue
        origens.append(origem)
    return origens


def _render_arquivos(origens: list[consolidacao.Origem]) -> None:
    st.subheader("Arquivos recebidos")
    for origem in origens:
        with st.container(border=True):
            cabecalho, tarja = st.columns([4, 2])
            cabecalho.markdown(f"**{origem.arquivo}**")
            with tarja:
                st.badge(_TEXTO_DO_STATUS.get(origem.status, origem.status),
                         color=_COR_DO_STATUS.get(origem.status, "gray"))

            if origem.status == consolidacao.IMAGEM:
                # §5: não inventar conteúdo, orientar o usuário.
                st.caption(
                    "Este PDF é uma digitalização: não tem texto para ler. "
                    "Peça à secretaria o arquivo em PDF de texto, ou lance "
                    "os itens à mão na planilha do processo. **Ele não "
                    "entra na soma** — e não conta como secretaria que "
                    "não pediu nada."
                )
                continue
            if origem.status != consolidacao.LIDO:
                st.caption(
                    "O arquivo abriu, mas não tem quadro de itens no "
                    "formato esperado. Confira se é mesmo um Documento de "
                    "Formalização de Demanda."
                )
                continue

            itens = sum(len(d.itens) for d in origem.dfds)
            documentos = ", ".join(d.numero for d in origem.dfds)
            st.caption(
                f"{len(origem.dfds)} documento(s) — nº {documentos} — "
                f"com **{itens}** itens no total."
            )
            if len(origem.dfds) > 1:
                # Explicar em vez de silenciar: o servidor precisa saber
                # que aquele arquivo carrega mais de uma demanda, porque
                # as quantidades somam entre elas.
                st.caption(
                    "Este arquivo traz mais de um documento de demanda. "
                    "As quantidades dos dois são somadas — são pedidos "
                    "distintos da mesma secretaria."
                )
            _render_rotulo(origem)


def _render_rotulo(origem: consolidacao.Origem) -> None:
    """
    §6: secretaria ambígua pede confirmação ANTES de consolidar.

    O campo aparece sempre, e não só na ambiguidade: quem confere pode
    discordar do que está escrito no documento, e corrigir ali é mais
    barato do que descobrir depois que a coluna saiu com o nome errado.
    """
    chave = f"demanda_rotulo_{origem.arquivo}"
    if ingestao.precisa_de_confirmacao(origem):
        st.warning(
            "Não consegui identificar o órgão dentro deste documento. "
            "Informe de qual secretaria ele é antes de consolidar."
        )
    novo = st.text_input(
        "Secretaria", value=origem.secretaria, key=chave,
        placeholder="Ex.: SEMEC",
        help="Sai do órgão declarado no documento. Corrija se estiver errado.",
    )
    if novo != origem.secretaria:
        st.session_state.setdefault(ROTULOS, {})[origem.arquivo] = novo
        st.rerun()


# ---------------------------------------------------------------------------
# Conflitos
# ---------------------------------------------------------------------------
def _render_conflitos(consolidado: consolidacao.Consolidado) -> None:
    if not consolidado.conflitos:
        return
    st.subheader("Conflitos que precisam da sua decisão")
    st.caption(
        "O mesmo código chegou com unidades diferentes. O sistema **não "
        "soma** nesses casos: converter caixa em unidade exigiria um "
        "fator que o documento não traz, e um total errado que parece "
        "certo é pior do que um conflito visível."
    )
    aceitos = set(st.session_state.setdefault(ACEITOS, []))
    for conflito in consolidado.conflitos:
        with st.container(border=True):
            st.markdown(
                f"**Item {conflito.codigo}** — chegou como "
                f"{', '.join(conflito.unidades)}, "
                f"de {', '.join(conflito.secretarias)}."
            )
            marcado = st.checkbox(
                "Manter as unidades separadas, cada uma na sua linha",
                value=conflito.codigo in aceitos,
                key=f"demanda_conflito_{conflito.codigo}",
                help="A decisão fica registrada no processo.",
            )
            if marcado:
                aceitos.add(conflito.codigo)
            else:
                aceitos.discard(conflito.codigo)
    st.session_state[ACEITOS] = sorted(aceitos)


# ---------------------------------------------------------------------------
# A tabela
# ---------------------------------------------------------------------------
def _render_tabela(consolidado: consolidacao.Consolidado) -> None:
    st.subheader("Tabela consolidada")
    secretarias = list(consolidado.secretarias)
    linhas = [
        {
            "Código": linha.codigo,
            "Descrição": linha.descricao,
            "Unidade": linha.unidade,
            **{s: float(linha.por_secretaria.get(s, 0)) for s in secretarias},
            "Total": float(linha.total),
        }
        for linha in consolidado.linhas
    ]
    # Tabela larga com doze secretarias não cabe em tela nenhuma; o
    # `st.dataframe` rola na horizontal sozinho, e o detalhamento por
    # item fica no expander abaixo — §11.
    st.dataframe(linhas, use_container_width=True, hide_index=True)

    with st.expander("Ver a origem de um item"):
        opcoes = {f"{l.codigo} — {l.descricao[:56]} ({l.unidade})": l
                  for l in consolidado.linhas}
        escolhido = st.selectbox("Item", list(opcoes), key="demanda_ver_origem")
        if escolhido:
            st.code(consolidacao.explicar(opcoes[escolhido]), language="text")


def _render_conferencia(consolidado: consolidacao.Consolidado) -> None:
    """
    §12: a soma é demonstrada, não afirmada.

    `conferir` refaz a conta a partir das parcelas — não do total — e é
    isso que a tela reporta.
    """
    laudo = consolidacao.conferir(consolidado)
    if laudo.fecha:
        st.success(
            f"**A conta fecha.** {len(consolidado.linhas)} itens, "
            f"{laudo.total_de_ocorrencias} parcelas somadas de "
            f"{len(consolidado.secretarias)} secretaria(s). Cada total foi "
            "reconferido a partir das parcelas."
        )
    else:
        st.error(
            "**A conta não fecha** e nada pode ser aplicado ao processo. "
            f"{laudo.divergencias[0]}"
        )
    if consolidado.duplicatas:
        st.caption(
            "Arquivos ignorados por serem reenvio do mesmo documento: "
            + ", ".join(consolidado.duplicatas)
        )


# ---------------------------------------------------------------------------
# Aplicar
# ---------------------------------------------------------------------------
def _render_acoes(consolidado: consolidacao.Consolidado) -> None:
    aplicar, baixar = st.columns(2)

    with baixar:
        st.download_button(
            "Baixar tabela consolidada (XLSX)",
            data=exportacao.planilha_consolidada(consolidado),
            file_name="demanda-consolidada.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            use_container_width=True,
        )

    with aplicar:
        if not st.button("Aplicar ao processo", type="primary",
                         use_container_width=True):
            return
    aceitos = tuple(st.session_state.get(ACEITOS) or ())
    dados = st.session_state.get("dados") or {}
    try:
        novos, resumo = aplicacao.aplicar(dados, consolidado,
                                          conflitos_aceitos=aceitos)
    except aplicacao.ErroAplicacao as erro:
        st.error(str(erro))
        return

    st.session_state["dados"] = novos
    st.success(
        f"**{resumo['itens']} itens** aplicados à planilha do processo, "
        f"somando {resumo['ocorrencias']} pedidos de "
        f"{resumo['secretarias']} secretaria(s). "
        "Siga para **Novo processo** para continuar a elaboração."
    )
    if resumo["nao_lidos"]:
        st.warning(
            "Fora da soma, porque não foram lidos: "
            + ", ".join(resumo["nao_lidos"])
        )


__all__ = ["disponivel", "render_demanda"]
