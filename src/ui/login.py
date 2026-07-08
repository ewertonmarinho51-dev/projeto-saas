"""
Tela de login, criação do administrador inicial e configuração necessária.
"""

import streamlit as st

from .. import auth, db


def render_configuracao_necessaria() -> None:
    """Sem Supabase: bloqueia o app e ensina a configurar (produção)."""
    st.subheader("Configuração necessária")
    st.warning(
        "O banco de dados não está conectado. Login, cadastro de usuários, "
        "Base de Conhecimento e identidade visual dependem do Supabase."
    )
    st.markdown(
        "**Como configurar o Supabase:**\n\n"
        "1. No painel do projeto Supabase, em **Settings → API**, copie a "
        "**Project URL** e a chave **publishable/anon**.\n"
        "2. Informe as duas no ambiente onde o app roda:\n"
        "   - Local: arquivo `.streamlit/secrets.toml`\n"
        "   - Streamlit Community Cloud: **Manage app → Settings → Secrets**\n\n"
        "```toml\n"
        'SUPABASE_URL = "https://SEU-PROJETO.supabase.co"\n'
        'SUPABASE_KEY = "sb_publishable_..."\n'
        "```\n\n"
        "3. Aplique as migrações em `supabase/migrations/` no **SQL Editor**.\n"
        "4. Recarregue esta página."
    )
    st.caption(
        "Apenas para desenvolvimento/CI sem banco: defina a variável de "
        "ambiente GOVDOCS_MODO_ABERTO=1 para liberar o app sem login."
    )
    url, _ = db._config()  # noqa: SLF001 — diagnóstico de conexão
    st.caption(f"Diagnóstico: SUPABASE_URL {'detectada' if url else 'ausente'}.")


def render_bootstrap_admin() -> None:
    """Primeiro acesso: nenhum administrador existe ainda."""
    st.subheader("Primeiro acesso: criar administrador")
    st.caption(
        "Nenhum administrador cadastrado. Crie a conta que irá gerenciar "
        "usuários, chaves de IA, identidade visual e a Base de Conhecimento."
    )
    with st.form("form_bootstrap"):
        nome = st.text_input("Nome completo")
        login = st.text_input("Login", help="Sem espaços; letras minúsculas.")
        senha = st.text_input("Senha", type="password",
                              help="Mínimo de 8 caracteres.")
        confirma = st.text_input("Confirmar senha", type="password")
        enviado = st.form_submit_button(
            "Criar administrador", type="primary", use_container_width=True
        )
    if enviado:
        if senha != confirma:
            st.error("As senhas não conferem.")
            return
        try:
            usuario = auth.criar_usuario(nome, login, senha, "admin")
            usuario.pop("senha_hash", None)
            st.session_state.usuario = usuario
            st.rerun()
        except auth.ErroAuth as erro:
            st.error(str(erro))


def render_login() -> None:
    st.subheader("Acesso ao sistema")
    st.caption(
        "Entre com suas credenciais. Contas são criadas pelo administrador."
    )
    with st.form("form_login"):
        login = st.text_input("Login")
        senha = st.text_input("Senha", type="password")
        enviado = st.form_submit_button(
            "Entrar", type="primary", use_container_width=True
        )
    if enviado:
        try:
            st.session_state.usuario = auth.autenticar(login, senha)
            st.rerun()
        except auth.ErroAuth as erro:
            st.error(str(erro))
