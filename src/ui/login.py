"""Portas de entrada: login, bootstrap administrativo e configuração."""

from __future__ import annotations

from collections.abc import Callable

import streamlit as st

from .. import auth, db
from . import components


def _layout_porta_entrada(conteudo: Callable[[], None]) -> None:
    painel_marca, painel_formulario = st.columns([52, 48], gap=None)
    with painel_marca:
        components.render_login_brand()
    with painel_formulario:
        components.render_login_panel_marker()
        conteudo()


def render_configuracao_necessaria() -> None:
    """Sem Supabase: bloqueia o app e orienta a configuração de produção."""

    def _conteudo() -> None:
        st.markdown('<p class="gc-login-module">GovDocs</p>',
                    unsafe_allow_html=True)
        st.subheader("Configuração necessária")
        st.warning(
            "O banco de dados não está conectado. Login, cadastro de usuários, "
            "Base de Conhecimento e identidade visual dependem do Supabase."
        )
        with st.expander("Como configurar o Supabase", expanded=True):
            st.markdown(
                "1. Em **Settings → API**, copie a **Project URL** e a chave "
                "**publishable/anon**.\n"
                "2. Informe-as em `.streamlit/secrets.toml` ou nos Secrets do "
                "Streamlit Community Cloud.\n\n"
                "```toml\n"
                'SUPABASE_URL = "https://SEU-PROJETO.supabase.co"\n'
                'SUPABASE_KEY = "sb_publishable_..."\n'
                "```\n"
                "3. Aplique as migrações de `supabase/migrations/` no SQL Editor.\n"
                "4. Recarregue esta página."
            )
        st.caption(
            "Para desenvolvimento/CI sem banco, defina "
            "GOVDOCS_MODO_ABERTO=1."
        )
        url, _ = db._config()  # noqa: SLF001 — diagnóstico de conexão
        st.caption(f"Diagnóstico: SUPABASE_URL {'detectada' if url else 'ausente'}.")

    _layout_porta_entrada(_conteudo)


def render_bootstrap_admin() -> None:
    """Primeiro acesso: cria a conta administrativa inicial."""

    def _conteudo() -> None:
        st.markdown('<p class="gc-login-module">GovDocs</p>',
                    unsafe_allow_html=True)
        st.subheader("Primeiro acesso: criar administrador")
        st.markdown(
            '<p class="gc-login-intro">Crie a conta institucional que irá '
            'gerenciar usuários e configurações.</p>',
            unsafe_allow_html=True,
        )
        with st.form("form_bootstrap"):
            nome = st.text_input("Nome completo", autocomplete="name")
            login = st.text_input("Login", help="Sem espaços; letras minúsculas.",
                                  autocomplete="username")
            senha = st.text_input("Senha", type="password",
                                  help="Mínimo de 8 caracteres.",
                                  autocomplete="new-password")
            confirma = st.text_input("Confirmar senha", type="password",
                                     autocomplete="new-password")
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
                auth.entrar(usuario)
                st.success("Administrador criado. Entrando no sistema…")
                st.rerun()
            except auth.ErroAuth as erro:
                st.error(str(erro))

    _layout_porta_entrada(_conteudo)


def render_login() -> None:
    """Autenticação institucional sem cadastro ou recuperação fictícios."""

    def _conteudo() -> None:
        st.markdown('<p class="gc-login-module">GovDocs</p>',
                    unsafe_allow_html=True)
        st.subheader("Acesso ao sistema")
        st.markdown(
            '<p class="gc-login-intro">Entre com suas credenciais institucionais.</p>',
            unsafe_allow_html=True,
        )
        usuario = st.text_input(
            "Usuário",
            key="_login_usuario",
            placeholder="Digite seu usuário",
            autocomplete="username",
        )
        senha = st.text_input(
            "Senha",
            key="_login_senha",
            type="password",
            placeholder="Digite sua senha",
            autocomplete="current-password",
        )
        pronto = bool(usuario.strip() and senha)
        enviado = st.button(
            "Entrar",
            type="primary",
            use_container_width=True,
            disabled=not pronto or st.session_state.get("_login_pendente", False),
            key="_login_enviar",
        )
        st.markdown(
            '<p class="gc-login-note">As contas de acesso são criadas pelo '
            'administrador.</p>',
            unsafe_allow_html=True,
        )

        if enviado:
            st.session_state["_login_pendente"] = True
            st.markdown(
                '<div class="gc-login-progress" role="status" aria-live="polite">'
                'Validando credenciais…</div>',
                unsafe_allow_html=True,
            )
            try:
                auth.entrar(auth.autenticar(usuario, senha))
                st.session_state.pop("_login_pendente", None)
                st.success("Acesso autorizado. Abrindo o sistema…")
                st.rerun()
            except auth.ErroAuth as erro:
                st.session_state["_login_pendente"] = False
                st.error(str(erro), icon=None)

        st.markdown(
            '<p class="gc-login-security">Acesso restrito e protegido</p>',
            unsafe_allow_html=True,
        )

    _layout_porta_entrada(_conteudo)
