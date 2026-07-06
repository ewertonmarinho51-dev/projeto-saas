"""
Telas de cada etapa do wizard:
  0 — Formulário Matriz
  1..4 — Geração + preview editável de DFD, ETP, TR e Edital
  5 — Sucesso e exportação (.docx / .pdf / .zip)
"""

import streamlit as st

from .. import export, state
from ..config import CAMPOS_FORMULARIO, DOCUMENTOS, SEQUENCIA_DOCUMENTOS
from ..llm import ErroGeracaoIA, gerar_documento
from .components import render_base_legal


# ---------------------------------------------------------------------------
# Etapa 0 — Formulário Matriz
# ---------------------------------------------------------------------------
def render_formulario() -> None:
    st.subheader("📋 Formulário Matriz — Dados da Demanda")
    st.caption(
        "Preencha as informações essenciais da contratação. Elas alimentarão "
        "a redação sequencial dos quatro documentos. Passe o mouse no ícone "
        "❓ de cada campo para ver o que a Lei nº 14.133/2021 espera."
    )

    dados = st.session_state.dados
    with st.form("formulario_matriz"):
        col1, col2 = st.columns(2)
        respostas: dict = {}

        # Distribui os campos em duas colunas para uma tela mais limpa
        colunas = {
            "orgao": col1, "responsavel": col2,
            "valor_estimado": col1, "modelo_execucao": col2, "prazo": col1,
        }
        for chave, meta in CAMPOS_FORMULARIO.items():
            destino = colunas.get(chave, st)
            rotulo = meta["rotulo"] + (" *" if meta["obrigatorio"] else "")
            if meta["tipo"] == "texto":
                respostas[chave] = destino.text_input(
                    rotulo, value=dados.get(chave, ""),
                    placeholder=meta["placeholder"], help=meta["help"],
                )
            elif meta["tipo"] == "area":
                respostas[chave] = st.text_area(
                    rotulo, value=dados.get(chave, ""), height=110,
                    placeholder=meta["placeholder"], help=meta["help"],
                )
            elif meta["tipo"] == "moeda":
                respostas[chave] = destino.number_input(
                    rotulo, min_value=0.0, step=1000.0, format="%.2f",
                    value=float(dados.get(chave, 0.0)), help=meta["help"],
                )
            elif meta["tipo"] == "selecao":
                opcoes = meta["opcoes"]
                atual = dados.get(chave, opcoes[0])
                respostas[chave] = destino.selectbox(
                    rotulo, opcoes,
                    index=opcoes.index(atual) if atual in opcoes else 0,
                    help=meta["help"],
                )

        enviado = st.form_submit_button(
            "Iniciar Elaboração dos Documentos ➜", type="primary",
            use_container_width=True,
        )

    if enviado:
        faltantes = [
            meta["rotulo"]
            for chave, meta in CAMPOS_FORMULARIO.items()
            if meta["obrigatorio"] and not respostas.get(chave)
        ]
        if faltantes:
            st.error(
                "Preencha os campos obrigatórios: **" + ", ".join(faltantes) + "**"
            )
            return
        if respostas != st.session_state.dados:
            # Dados mudaram: documentos já gerados ficam obsoletos
            state.invalidar_a_partir_de("formulario")
        st.session_state.dados = respostas
        state.ir_para(1)


# ---------------------------------------------------------------------------
# Etapas 1..4 — Geração e preview editável de cada documento
# ---------------------------------------------------------------------------
def render_etapa_documento(doc_key: str) -> None:
    meta = DOCUMENTOS[doc_key]
    st.subheader(f"📝 {meta['titulo']} ({meta['sigla']})")
    render_base_legal(f"Base legal: {meta['base_legal']} — {meta['descricao']}")

    contexto_key = meta["usa_contexto_de"]
    contexto = st.session_state.documentos.get(contexto_key) if contexto_key else None

    # ---------- Documento ainda não gerado: tela de geração ----------
    if doc_key not in st.session_state.documentos:
        if contexto_key:
            st.info(
                f"Este documento será redigido pela IA usando o formulário e o "
                f"**{DOCUMENTOS[contexto_key]['sigla']} aprovado** como contexto.",
                icon="🔗",
            )
        if st.button(
            f"✨ Gerar {meta['sigla']} com IA", type="primary",
            use_container_width=True,
        ):
            with st.spinner(
                f"Redigindo o {meta['sigla']}… isso pode levar até 2 minutos."
            ):
                try:
                    texto = gerar_documento(doc_key, st.session_state.dados, contexto)
                    st.session_state.documentos[doc_key] = texto
                    st.rerun()
                except ErroGeracaoIA as erro:
                    st.error(str(erro), icon="🚫")
        _botao_voltar(meta)
        return

    # ---------- Preview editável (controle humano obrigatório) ----------
    st.success(
        "Rascunho gerado. **Revise e edite livremente o texto abaixo** — nada "
        "avança sem a sua aprovação.",
        icon="👁️",
    )
    aba_editar, aba_visualizar = st.tabs(["✏️ Editar", "👁️ Visualizar formatado"])
    with aba_editar:
        texto_editado = st.text_area(
            "Conteúdo do documento (editável)",
            value=st.session_state.documentos[doc_key],
            height=480,
            key=f"editor_{doc_key}",
            label_visibility="collapsed",
        )
    with aba_visualizar:
        st.markdown(texto_editado)

    col_voltar, col_regerar, col_aprovar = st.columns([1, 1, 2])
    if col_voltar.button("⬅ Voltar", use_container_width=True, key=f"volta_{doc_key}"):
        st.session_state.documentos[doc_key] = texto_editado  # preserva edições
        state.ir_para(meta["etapa"] - 1)
    if col_regerar.button(
        "🔄 Gerar novamente", use_container_width=True, key=f"regera_{doc_key}",
        help="Descarta este rascunho e solicita nova redação à IA.",
    ):
        state.descartar_documento(doc_key)
        st.rerun()
    if col_aprovar.button(
        f"✅ Aprovar {meta['sigla']} e Avançar ➜", type="primary",
        use_container_width=True, key=f"aprova_{doc_key}",
    ):
        # Se o texto mudou em relação ao aprovado antes, invalida os seguintes
        if st.session_state.documentos.get(doc_key) != texto_editado:
            state.invalidar_a_partir_de(doc_key)
        state.aprovar_e_avancar(doc_key, texto_editado)


def _botao_voltar(meta: dict) -> None:
    if st.button("⬅ Voltar", key=f"volta_vazio_{meta['sigla']}"):
        state.ir_para(meta["etapa"] - 1)


# ---------------------------------------------------------------------------
# Etapa 5 — Sucesso e exportação
# ---------------------------------------------------------------------------
def render_sucesso() -> None:
    st.balloons()
    st.subheader("🎉 Processo concluído com sucesso!")
    st.markdown(
        "Os **quatro documentos da fase preparatória** foram elaborados e "
        "aprovados. Baixe o dossiê completo ou os arquivos individuais."
    )

    docs = st.session_state.documentos
    orgao = (st.session_state.dados.get("orgao") or "orgao").strip()
    prefixo = "".join(c if c.isalnum() else "-" for c in orgao)[:40].strip("-") or "dossie"

    st.markdown("#### 📦 Dossiê completo (arquivo único)")
    col_pdf, col_docx = st.columns(2)
    col_pdf.download_button(
        "⬇️ Baixar todos em PDF",
        data=export.gerar_pdf_consolidado(docs),
        file_name=f"{prefixo}-fase-preparatoria.pdf",
        mime="application/pdf",
        type="primary", use_container_width=True,
    )
    col_docx.download_button(
        "⬇️ Baixar todos em DOCX",
        data=export.gerar_docx_consolidado(docs),
        file_name=f"{prefixo}-fase-preparatoria.docx",
        mime="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        type="primary", use_container_width=True,
    )

    st.markdown("#### 🗂️ Arquivos individuais (pacote .zip)")
    col_zip_pdf, col_zip_docx = st.columns(2)
    col_zip_pdf.download_button(
        "⬇️ ZIP com os 4 PDFs",
        data=export.gerar_zip(docs, "pdf"),
        file_name=f"{prefixo}-documentos-pdf.zip",
        mime="application/zip", use_container_width=True,
    )
    col_zip_docx.download_button(
        "⬇️ ZIP com os 4 DOCX",
        data=export.gerar_zip(docs, "docx"),
        file_name=f"{prefixo}-documentos-docx.zip",
        mime="application/zip", use_container_width=True,
    )

    with st.expander("👁️ Conferir documentos aprovados"):
        abas = st.tabs([DOCUMENTOS[k]["sigla"] for k in SEQUENCIA_DOCUMENTOS if k in docs])
        for aba, doc_key in zip(abas, [k for k in SEQUENCIA_DOCUMENTOS if k in docs]):
            with aba:
                st.markdown(docs[doc_key])

    st.divider()
    col_rev, col_novo = st.columns(2)
    if col_rev.button("⬅ Voltar para revisar a minuta", use_container_width=True):
        state.ir_para(4)
    if col_novo.button("🆕 Iniciar novo processo", use_container_width=True):
        state.reiniciar_processo()
