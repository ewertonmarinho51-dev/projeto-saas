"""
Página "Base de Conhecimento" — gestão dos documentos de referência do RAG.

Permite enviar leis, acórdãos, entendimentos dos Tribunais de Contas,
processos anteriores e modelos (PDF/DOCX/TXT/MD), acompanhar o que está
indexado, testar a busca e excluir referências.
"""

import streamlit as st

from .. import db, rag


def render_biblioteca() -> None:
    st.subheader("Base de Conhecimento (RAG)")
    st.caption(
        "Envie leis, acórdãos, entendimentos dos Tribunais de Contas, "
        "processos anteriores e modelos. A IA recupera os trechos mais "
        "relevantes desses arquivos para fundamentar cada documento gerado."
    )

    if not db.disponivel():
        st.warning(
            "Configure SUPABASE_URL e SUPABASE_KEY em .streamlit/secrets.toml "
            "para habilitar a Base de Conhecimento.",
        )
        return

    # ---------------- Envio e indexação ----------------
    with st.form("form_indexar", clear_on_submit=True):
        st.markdown("##### Adicionar referências")
        arquivos = st.file_uploader(
            "Arquivos (PDF, DOCX, TXT, MD)",
            type=["pdf", "docx", "txt", "md"],
            accept_multiple_files=True,
            help=(
                "Ex.: Lei 14.133/2021 anotada, Acórdãos do TCU, orientações do "
                "seu TCE, ETPs e TRs de contratações anteriores, modelos da AGU."
            ),
        )
        col_cat, col_tit = st.columns(2)
        categoria = col_cat.selectbox(
            "Categoria",
            options=list(rag.CATEGORIAS),
            format_func=lambda c: rag.CATEGORIAS[c],
            help="A categoria orienta como a IA usa o material: normas e "
            "acórdãos são citáveis; processos e modelos são padrão de redação.",
        )
        titulo = col_tit.text_input(
            "Título (opcional — um por lote)",
            placeholder="Ex.: Acórdão TCU 1234/2024-Plenário",
            help="Se vazio, usa o nome de cada arquivo.",
        )
        enviar = st.form_submit_button(
            "Indexar na Base de Conhecimento", type="primary",
            use_container_width=True,
        )

    if enviar:
        if not arquivos:
            st.error("Selecione ao menos um arquivo.")
        else:
            for arquivo in arquivos:
                try:
                    with st.spinner(f"Indexando {arquivo.name}…"):
                        n = rag.indexar_arquivo(
                            arquivo.name,
                            titulo if len(arquivos) == 1 else "",
                            categoria,
                            arquivo.getvalue(),
                        )
                    st.success(f"{arquivo.name}: {n} trechos indexados.")
                except rag.ErroRAG as erro:
                    st.error(f"{arquivo.name}: {erro}")

    st.divider()

    # ---------------- Referências indexadas ----------------
    st.markdown("##### Referências indexadas")
    try:
        referencias = rag.listar_referencias()
    except rag.ErroRAG as erro:
        st.error(str(erro))
        if "does not exist" in str(erro) or "42P01" in str(erro):
            st.info(
                "Parece que as tabelas da Base de Conhecimento ainda não "
                "existem — aplique a migração "
                "`supabase/migrations/0003_base_conhecimento_rag.sql` no "
                "SQL Editor do painel Supabase.",
            )
        return

    if not referencias:
        st.caption("Nenhuma referência indexada ainda.")
    for ref in referencias:
        col_info, col_meta, col_acao = st.columns([5, 2, 1])
        rotulo = rag.CATEGORIAS.get(ref["categoria"], ref["categoria"])
        col_info.markdown(f"**{ref['titulo']}**  \n{rotulo} · `{ref['nome_arquivo']}`")
        col_meta.caption(
            f"{ref['total_chunks']} trechos\n\n{(ref['criado_em'] or '')[:10]}"
        )
        if col_acao.button("Excluir", key=f"del_ref_{ref['id']}"):
            try:
                rag.excluir_referencia(ref["id"])
                st.rerun()
            except rag.ErroRAG as erro:
                st.error(str(erro))

    # ---------------- Teste de busca ----------------
    st.divider()
    with st.expander("Testar a recuperação (o que a IA veria)"):
        consulta = st.text_input(
            "Consulta de teste",
            placeholder="Ex.: registro de preços para aquisição de equipamentos de TI",
        )
        if consulta:
            try:
                trechos = rag.buscar_referencias(consulta)
                if not trechos:
                    st.caption("Nenhum trecho relevante encontrado.")
                for t in trechos:
                    st.markdown(
                        f"**{t.get('titulo', '')}** "
                        f"({rag.CATEGORIAS.get(t.get('categoria', ''), '')}) — "
                        f"relevância {t.get('similaridade', 0):.2f}"
                    )
                    st.caption((t.get("conteudo") or "")[:400] + "…")
            except rag.ErroRAG as erro:
                st.error(str(erro))
