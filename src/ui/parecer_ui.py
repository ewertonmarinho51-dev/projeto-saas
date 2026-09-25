"""
Anexar Parecer Jurídico — a tela.

§17: um processo já salvo recebe depois um parecer, e o sistema corrige
o que for objetivamente corrigível. A tela é a superfície disso, e o
desenho dela tem uma regra que atravessa tudo: **nada é aplicado antes
de o servidor ver o plano inteiro**.

O motivo é o §22. O parecer é lido, classificado e planejado por
completo antes da primeira alteração — então mostrar o plano custa zero
e evita o pior cenário do produto, que é o servidor descobrir depois que
o sistema mexeu em cinco cláusulas, uma delas errada.

Por isso a tela tem duas etapas separadas por um clique:

    anexar → analisar → **ver o plano** → aplicar → relatório → desfazer

E o botão de aplicar nunca aparece antes do plano.

O que a tela não mostra
-----------------------
§33: nada de prompt, JSON, token ou SQL. O servidor lê "Lendo o parecer
jurídico", não o corpo da chamada. O texto do parecer é dado de entrada
e continua sendo tratado como tal — nenhum trecho dele vira instrução
para o sistema, e o relatório mostra o que ele PEDE, não o executa.
"""

from __future__ import annotations

import streamlit as st

from .. import auth, contexto, db, governanca, pareceres, parecer_correcao as pc
from . import components

PLANO = "parecer_plano"
RESULTADO = "parecer_resultado"
ANTES = "parecer_documentos_antes"

# §33 — o que a tela diz enquanto trabalha. São frases de servidor, não
# etapas de pipeline.
PASSOS = (
    "Lendo o parecer jurídico",
    "Identificando os apontamentos",
    "Localizando os documentos afetados",
    "Preparando as correções",
)

_COR = {
    pc.CORRECAO_AUTOMATICA: "green",
    pc.JA_ATENDIDO: "blue",
    pc.EXIGE_DADO_FALTANTE: "orange",
    pc.EXIGE_DECISAO_ADMINISTRATIVA: "orange",
    pc.AMBIGUO: "violet",
    pc.CONFLITANTE: "red",
    pc.NAO_APLICAVEL: "gray",
}


def disponivel() -> bool:
    """
    Os três níveis (§39). Nasce desligada, como o §34 pede.

    Antes olhava só a flag global, e o item aparecia no menu mesmo para
    uma secretaria que tinha desabilitado o módulo no painel.
    """
    return contexto.modulo_disponivel_aqui(governanca.FLAG_CORRECAO_PARECER)


def render_parecer() -> None:
    components.render_page_header(
        "Parecer Jurídico",
        "Anexe o parecer e o sistema corrige o que for objetivamente "
        "corrigível — e diz o que depende de você.",
    )

    documentos = st.session_state.get("documentos") or {}
    if not documentos:
        st.info(
            "Abra um processo que já tenha documentos gerados. Vá em "
            "**Processos**, clique em *Continuar de onde parei* e volte aqui."
        )
        return

    st.caption(
        f"Processo aberto com {len(documentos)} documento(s): "
        + ", ".join(sorted(d.upper() for d in documentos))
    )

    if st.session_state.get(RESULTADO):
        _render_resultado()
        return
    if st.session_state.get(PLANO):
        _render_plano()
        return
    _render_anexar(documentos)


# ---------------------------------------------------------------------------
# 1. Anexar e analisar
# ---------------------------------------------------------------------------
def _render_anexar(documentos: dict) -> None:
    arquivo = st.file_uploader(
        "Parecer jurídico (PDF ou DOCX)", type=["pdf", "docx"],
        key="parecer_arquivo",
        help="O mesmo arquivo enviado duas vezes é reconhecido e não "
             "analisado de novo.",
    )
    if not arquivo:
        return
    if not st.button("Analisar o parecer", type="primary"):
        return

    barra = st.progress(0.0)
    aviso = st.empty()
    try:
        aviso.caption(PASSOS[0])
        barra.progress(0.25)
        parecer = pareceres.ingerir(arquivo.name, arquivo.getvalue(),
                                    processo_id=st.session_state.get("processo_id"))

        aviso.caption(PASSOS[1])
        barra.progress(0.5)
        achados = pareceres.analisar(parecer)

        aviso.caption(PASSOS[2])
        barra.progress(0.75)
        plano = pc.planejar(achados, documentos,
                            st.session_state.get("dados") or {})

        aviso.caption(PASSOS[3])
        barra.progress(1.0)
    except (pareceres.ErroParecer, db.ErroBanco) as erro:
        barra.empty()
        aviso.empty()
        st.error(str(erro))
        return
    except Exception:  # noqa: BLE001
        # §33: detalhe técnico não vai para a tela. O incidente fica
        # registrado no servidor pelo caminho de sempre.
        barra.empty()
        aviso.empty()
        st.error(
            "Não foi possível analisar este parecer. O detalhe técnico "
            "ficou registrado no servidor."
        )
        return

    barra.empty()
    aviso.empty()
    st.session_state[PLANO] = plano
    st.session_state[ANTES] = dict(documentos)
    st.rerun()


# ---------------------------------------------------------------------------
# 2. O plano, antes de qualquer alteração
# ---------------------------------------------------------------------------
def _render_plano() -> None:
    plano = st.session_state[PLANO]
    placar = pc.contagem(plano)
    automaticos = placar.get(pc.CORRECAO_AUTOMATICA, 0)

    components.render_section_heading(
        "O que o parecer pede",
        "Nada foi alterado ainda. Confira antes de aplicar.",
    )
    st.markdown(
        f"**{len(plano.apontamentos)} apontamentos** identificados — "
        f"{automaticos} podem ser corrigidos automaticamente."
    )

    for apontamento in plano.apontamentos:
        _render_apontamento(apontamento)

    if not automaticos:
        st.info(
            "Nenhuma correção automática neste parecer. Os apontamentos "
            "acima dependem de você — o sistema não decide no seu lugar."
        )
    aplicar, cancelar = st.columns(2)
    if automaticos and aplicar.button(
            f"Aplicar as {automaticos} correções automáticas",
            type="primary", use_container_width=True):
        _aplicar(plano)
    if cancelar.button("Descartar este parecer", use_container_width=True):
        _limpar()
        st.rerun()


def _render_apontamento(a) -> None:
    with st.container(border=True):
        cabecalho, tarja = st.columns([4, 2])
        alvo = f"{a.documento.upper()} — {a.clausula}" if a.clausula else a.documento.upper()
        cabecalho.markdown(f"**{a.id}** · {alvo}")
        with tarja:
            st.badge(pc.ROTULO_DA_SITUACAO.get(a.situacao, a.situacao),
                     color=_COR.get(a.situacao, "gray"))
        st.markdown(f"*O parecer diz:* {a.problema}")
        if a.recomendacao:
            st.markdown(f"*Recomenda:* {a.recomendacao}")
        if a.fundamento:
            st.caption(f"Fundamento citado: {a.fundamento}")
        if a.motivo:
            # O motivo é a parte acionável: diz o que falta para sair do
            # estado em que está.
            st.caption(f"**Por que não é automático:** {a.motivo}")


# ---------------------------------------------------------------------------
# 3. Aplicar
# ---------------------------------------------------------------------------
def _aplicar(plano) -> None:
    documentos = st.session_state.get("documentos") or {}
    aprovados = st.session_state.get("aprovados") or set()
    with st.spinner("Aplicando as correções e revisando a consistência…"):
        resultado = pc.aplicar(plano, documentos, aprovados)

    st.session_state["documentos"] = resultado["documentos"]
    # §26: documento alterado perde a aprovação. Quem aprovou aprovou
    # outro texto.
    st.session_state["aprovados"] = resultado["aprovados"]
    st.session_state[RESULTADO] = resultado
    st.rerun()


# ---------------------------------------------------------------------------
# 4. Relatório de atendimento e desfazer
# ---------------------------------------------------------------------------
def _render_resultado() -> None:
    resultado = st.session_state[RESULTADO]
    relatorio = resultado["relatorio"]
    plano = st.session_state[PLANO]

    components.render_section_heading(
        "Relatório de atendimento",
        "O que foi feito com cada apontamento do parecer.",
    )
    placar = relatorio["por_situacao"]
    st.markdown(
        f"**{relatorio['total']} apontamentos** · "
        f"{relatorio['atendidos']} corrigidos · "
        f"{placar.get(pc.EXIGE_DADO_FALTANTE, 0)} exigem informação · "
        f"{placar.get(pc.EXIGE_DECISAO_ADMINISTRATIVA, 0)} exigem decisão sua · "
        f"{relatorio['falharam']} falharam"
    )

    alterados = resultado.get("alterados") or ()
    if alterados:
        st.warning(
            f"**{pc.CARIMBO_PENDENTE}** — "
            + ", ".join(d.upper() for d in alterados)
            + ". A aprovação anterior desses documentos foi retirada: "
            "quem aprovou aprovou outro texto."
        )

    for linha in relatorio["apontamentos"]:
        with st.container(border=True):
            st.markdown(
                f"**{linha['id']}** · {linha['documento'].upper()} "
                f"{linha['clausula']}".strip()
            )
            st.caption(linha["rotulo"])
            st.markdown(f"*Parecer:* {linha['parecer']}")
            if linha["detalhe"]:
                st.caption(linha["detalhe"])

    _render_diff(resultado)

    desfazer, concluir = st.columns(2)
    if desfazer.button("Desfazer as correções deste parecer",
                       use_container_width=True):
        try:
            st.session_state["documentos"] = pc.desfazer(plano)
        except pc.ErroCorrecaoParecer as erro:
            st.error(str(erro))
            return
        _limpar()
        st.success("Os documentos voltaram como estavam antes do parecer.")
        st.rerun()
    if concluir.button("Concluir", type="primary", use_container_width=True):
        _limpar()
        st.rerun()


def _render_diff(resultado: dict) -> None:
    """
    §29: o servidor não deve reler dezenas de páginas para descobrir o
    que mudou.
    """
    diff = resultado.get("diff") or {}
    alterados = [p for p, b in (diff.get("blocos") or {}).items()
                 if b.get("estado") != "igual"]
    if not alterados:
        return
    with st.expander(f"Ver o que mudou ({len(alterados)} trecho(s))"):
        antes = st.session_state.get(ANTES) or {}
        depois = st.session_state.get("documentos") or {}
        for doc in sorted({p.split("/")[0] for p in alterados}):
            st.markdown(f"#### {doc.upper()}")
            esquerda, direita = st.columns(2)
            esquerda.caption("Antes")
            esquerda.code(antes.get(doc, "")[:2000], language="text")
            direita.caption("Depois")
            direita.code(depois.get(doc, "")[:2000], language="text")


def _limpar() -> None:
    for chave in (PLANO, RESULTADO, ANTES):
        st.session_state.pop(chave, None)


__all__ = ["disponivel", "render_parecer"]
