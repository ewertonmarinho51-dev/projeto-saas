"""
Telas de cada etapa do wizard:
  0 — Formulário Matriz
  1..4 — Geração + preview editável de DFD, ETP, TR e Edital
  5 — Conclusão e exportação (.docx / .pdf / .zip)
"""

import streamlit as st

from .. import db, export, planilha, state
from ..config import CAMPOS_FORMULARIO, DOCUMENTOS, SEQUENCIA_DOCUMENTOS
from ..llm import ErroGeracaoIA, gerar_documento
from .components import render_base_legal


def _render_planilha(dados: dict, meta: dict) -> list[dict]:
    """Editor da planilha orçamentária dentro do formulário matriz."""
    st.markdown(f"**{meta['rotulo']} \\***")
    st.caption(meta["help"])
    st.caption(
        "A coluna **Fonte / Link** já está disponível: cole o link de onde o "
        "preço foi obtido — no documento ele aparece compacto como 'link', "
        "mas continua clicável. Colunas adicionais (ex.: Marca) são "
        "preservadas quando você importa a planilha de um arquivo Excel."
    )

    # Colunas fixas editáveis + Fonte/Link + colunas extras vindas do XLSX.
    # O valor total e o valor global são derivados automaticamente.
    base_itens = dados.get("itens") or planilha.linhas_iniciais()
    extras = [e for e in planilha.colunas_extra(base_itens)
              if e != planilha.CAMPO_FONTE]
    colunas = planilha.CAMPOS_ITEM + [planilha.CAMPO_FONTE] + extras

    base = [{c: it.get(c, "") for c in colunas} for it in base_itens]

    config = {
        "codigo": st.column_config.TextColumn(planilha.ROTULOS["codigo"], width="small"),
        "descricao": st.column_config.TextColumn(planilha.ROTULOS["descricao"], width="large"),
        "unidade": st.column_config.TextColumn(planilha.ROTULOS["unidade"], width="small"),
        "quantidade": st.column_config.NumberColumn(
            planilha.ROTULOS["quantidade"], min_value=0.0, step=1.0, format="%.2f"),
        "valor_unitario": st.column_config.NumberColumn(
            planilha.ROTULOS["valor_unitario"], min_value=0.0, step=100.0, format="%.2f"),
        planilha.CAMPO_FONTE: st.column_config.LinkColumn(
            planilha.ROTULOS["fonte"], display_text="link",
            help="Cole o link de onde o preço foi obtido. No documento aparece "
            "compacto como 'link', mas continua clicável."),
    }
    for c in extras:
        config[c] = st.column_config.TextColumn(c)

    # a key muda ao importar XLSX ou ao adicionar coluna, forçando recarga
    versao = f"{st.session_state.get('_xlsx_lido') or 'manual'}_{len(colunas)}"
    editado = st.data_editor(
        base, key=f"editor_itens_{versao}", num_rows="dynamic",
        use_container_width=True, column_config=config,
    )
    itens = editado.to_dict("records") if hasattr(editado, "to_dict") else list(editado)
    _, valor_global = planilha.calcular(itens)
    st.caption(
        f"Valor global (estimativa): **{planilha.formatar_moeda(valor_global)}** "
        "— recalculado ao avançar."
    )
    return itens


# ---------------------------------------------------------------------------
# Etapa 0 — Formulário Matriz
# ---------------------------------------------------------------------------
def render_formulario() -> None:
    st.subheader("Formulário Matriz: dados da demanda")
    st.caption(
        "Preencha as informações essenciais da contratação. Elas alimentarão "
        "a redação sequencial dos quatro documentos. O ícone de ajuda de "
        "cada campo explica o que a Lei nº 14.133/2021 espera."
    )

    dados = st.session_state.dados

    # Importação opcional da planilha via XLSX (fora do form, para
    # re-semear a tabela imediatamente após o upload)
    with st.expander("Importar planilha de um arquivo Excel (.xlsx)"):
        st.caption(
            "Opcional. Envie a planilha ANTES de preencher os demais campos. "
            "Colunas reconhecidas: código, descrição, unidade, quantidade e "
            "valor unitário (aceita variações de nome). O valor total e o "
            "valor global são recalculados."
        )
        st.download_button(
            "Baixar modelo de planilha (.xlsx)",
            data=planilha.modelo_xlsx(),
            file_name="modelo-planilha-orcamentaria.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            key="btn_modelo_xlsx",
        )
        arquivo = st.file_uploader("Arquivo .xlsx", type=["xlsx"], key="upload_itens")
        if arquivo is not None and st.session_state.get("_xlsx_lido") != arquivo.file_id:
            try:
                importados = planilha.importar_de_xlsx(arquivo.getvalue())
                dados["itens"] = importados
                st.session_state.dados = dados
                st.session_state["_xlsx_lido"] = arquivo.file_id
                st.success(f"{len(importados)} itens importados da planilha.")
                st.rerun()
            except planilha.ErroPlanilha as erro:
                st.error(str(erro))

    with st.form("formulario_matriz"):
        col1, col2 = st.columns(2)
        respostas: dict = {}

        # Distribui os campos simples em duas colunas para uma tela mais limpa
        colunas = {
            "orgao": col1, "responsavel": col2,
            "modelo_execucao": col2, "prazo": col1,
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
            elif meta["tipo"] == "planilha":
                respostas["itens"] = _render_planilha(dados, meta)
            elif meta["tipo"] == "selecao":
                opcoes = meta["opcoes"]
                atual = dados.get(chave, opcoes[0])
                respostas[chave] = destino.selectbox(
                    rotulo, opcoes,
                    index=opcoes.index(atual) if atual in opcoes else 0,
                    help=meta["help"],
                )

        enviado = st.form_submit_button(
            "Iniciar elaboração dos documentos", type="primary",
            use_container_width=True,
        )

    if enviado:
        # Consolida a planilha: calcula totais e o valor global (estimativa)
        itens, valor_global = planilha.calcular(respostas.get("itens") or [])
        respostas["itens"] = itens
        respostas["valor_estimado"] = valor_global

        faltantes = []
        for chave, meta in CAMPOS_FORMULARIO.items():
            if not meta["obrigatorio"]:
                continue
            if chave == "itens":
                if not itens:
                    faltantes.append(meta["rotulo"])
            elif not respostas.get(chave):
                faltantes.append(meta["rotulo"])
        if faltantes:
            st.error(
                "Preencha os campos obrigatórios: **" + ", ".join(faltantes) + "**"
            )
            return
        if respostas != st.session_state.dados:
            # Dados mudaram: documentos já gerados ficam obsoletos
            state.invalidar_a_partir_de("formulario")
        st.session_state.dados = respostas
        st.session_state.etapa = 1
        state.autosalvar()  # cria/atualiza o processo no Supabase
        st.rerun()


# ---------------------------------------------------------------------------
# Etapas 1..4 — Geração e preview editável de cada documento
# ---------------------------------------------------------------------------
def render_etapa_documento(doc_key: str) -> None:
    meta = DOCUMENTOS[doc_key]
    st.subheader(f"{meta['titulo']} ({meta['sigla']})")
    render_base_legal(f"Base legal: {meta['base_legal']}. {meta['descricao']}")

    contexto_key = meta["usa_contexto_de"]
    contexto = st.session_state.documentos.get(contexto_key) if contexto_key else None

    # ---------- Documento ainda não gerado: tela de geração ----------
    if doc_key not in st.session_state.documentos:
        if contexto_key:
            st.info(
                f"Este documento será redigido pela IA usando o formulário e o "
                f"**{DOCUMENTOS[contexto_key]['sigla']} aprovado** como contexto."
            )
        if st.button(
            f"Gerar {meta['sigla']} com IA", type="primary",
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
                    st.error(str(erro))
                    detalhe = getattr(erro, "detalhe", "")
                    if detalhe:
                        with st.expander("Detalhes técnicos (erro bruto da API)"):
                            st.code(detalhe)
        _botao_voltar(meta)
        return

    # ---------- Preview editável (controle humano obrigatório) ----------
    st.success(
        "Rascunho gerado. **Revise e edite livremente o texto abaixo.** Nada "
        "avança sem a sua aprovação."
    )
    aba_editar, aba_visualizar = st.tabs(["Editar", "Visualizar formatado"])
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
    if col_voltar.button("Voltar", use_container_width=True, key=f"volta_{doc_key}"):
        st.session_state.documentos[doc_key] = texto_editado  # preserva edições
        state.ir_para(meta["etapa"] - 1)
    if col_regerar.button(
        "Gerar novamente", use_container_width=True, key=f"regera_{doc_key}",
        help="Descarta este rascunho e solicita nova redação à IA.",
    ):
        state.descartar_documento(doc_key)
        st.rerun()
    if col_aprovar.button(
        f"Aprovar {meta['sigla']} e avançar", type="primary",
        use_container_width=True, key=f"aprova_{doc_key}",
    ):
        # Se o texto mudou em relação ao aprovado antes, invalida os seguintes
        if st.session_state.documentos.get(doc_key) != texto_editado:
            state.invalidar_a_partir_de(doc_key)
        state.aprovar_e_avancar(doc_key, texto_editado)


def _botao_voltar(meta: dict) -> None:
    if st.button("Voltar", key=f"volta_vazio_{meta['sigla']}"):
        state.ir_para(meta["etapa"] - 1)


# ---------------------------------------------------------------------------
# Etapa 5 — Conclusão e exportação
# ---------------------------------------------------------------------------
def render_sucesso() -> None:
    st.subheader("Processo concluído")
    st.markdown(
        "Os **quatro documentos da fase preparatória** foram elaborados e "
        "aprovados. Baixe o dossiê completo ou os arquivos individuais."
    )

    docs = st.session_state.documentos
    orgao = (st.session_state.dados.get("orgao") or "orgao").strip()
    prefixo = "".join(c if c.isalnum() else "-" for c in orgao)[:40].strip("-") or "dossie"

    # Identidade visual (cabeçalho/rodapé/marca d'água) definida pelo admin
    branding = None
    if db.disponivel():
        try:
            orgaos = db.listar_orgaos()
        except db.ErroBanco:
            orgaos = []
        if orgaos:
            rotulos = {o["orgao"]: o for o in orgaos}
            escolha = st.selectbox(
                "Identidade visual dos arquivos",
                ["Sem identidade visual", *rotulos],
                index=1,  # a padrão vem primeiro na listagem
                help="Cabeçalho e rodapé em todas as páginas; marca d'água no PDF.",
            )
            if escolha != "Sem identidade visual":
                branding = rotulos[escolha]

    st.markdown("#### Dossiê completo (arquivo único)")
    col_pdf, col_docx = st.columns(2)
    col_pdf.download_button(
        "Baixar todos em PDF",
        data=export.gerar_pdf_consolidado(docs, branding),
        file_name=f"{prefixo}-fase-preparatoria.pdf",
        mime="application/pdf",
        type="primary", use_container_width=True,
    )
    col_docx.download_button(
        "Baixar todos em DOCX",
        data=export.gerar_docx_consolidado(docs, branding),
        file_name=f"{prefixo}-fase-preparatoria.docx",
        mime="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        type="primary", use_container_width=True,
    )

    st.markdown("#### Arquivos individuais (pacote .zip)")
    col_zip_pdf, col_zip_docx = st.columns(2)
    col_zip_pdf.download_button(
        "ZIP com os 4 PDFs",
        data=export.gerar_zip(docs, "pdf", branding),
        file_name=f"{prefixo}-documentos-pdf.zip",
        mime="application/zip", use_container_width=True,
    )
    col_zip_docx.download_button(
        "ZIP com os 4 DOCX",
        data=export.gerar_zip(docs, "docx", branding),
        file_name=f"{prefixo}-documentos-docx.zip",
        mime="application/zip", use_container_width=True,
    )

    with st.expander("Conferir documentos aprovados"):
        abas = st.tabs([DOCUMENTOS[k]["sigla"] for k in SEQUENCIA_DOCUMENTOS if k in docs])
        for aba, doc_key in zip(abas, [k for k in SEQUENCIA_DOCUMENTOS if k in docs]):
            with aba:
                st.markdown(docs[doc_key])

    st.divider()
    col_rev, col_novo = st.columns(2)
    if col_rev.button("Voltar para revisar a minuta", use_container_width=True):
        state.ir_para(4)
    if col_novo.button("Iniciar novo processo", use_container_width=True):
        state.reiniciar_processo()
