"""
Tela de login e criação do administrador inicial (primeiro acesso).
"""

import streamlit as st

from .. import auth


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
