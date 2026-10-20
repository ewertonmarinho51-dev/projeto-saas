"""Portas de entrada: login, bootstrap administrativo, manutenção e
configuração."""

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


def render_manutencao() -> None:
    """
    Falha FECHADA: sem a credencial de servidor obrigatória o app não
    opera em modo degradado. Nada de login, persistência, aprovação,
    geração oficial ou emissão — e nenhum fallback para a chave
    publicável.

    A tela é deliberadamente pobre em diagnóstico: quem precisa da
    instrução técnica é o operador do servidor, que a encontra no
    runbook (`docs/seguranca-achado-p0.md`), não o visitante.
    """
    st.subheader("Sistema em manutenção")
    st.error(
        "O GovDocs está temporariamente indisponível por manutenção "
        "programada de segurança. Nenhum documento pode ser gerado, "
        "aprovado ou emitido neste momento."
    )
    st.caption(
        "Se você é o responsável técnico pelo servidor, consulte o "
        "procedimento de contenção em `docs/seguranca-achado-p0.md`."
    )


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


# O login só guarda o USUÁRIO entre tentativas, e fora de widget: é o
# valor inicial do campo depois de uma recusa. A senha não tem chave de
# estado nenhuma — vive o tempo de uma submissão e o `clear_on_submit`
# a apaga do campo. Antes, `_login_senha` ficava em `session_state` até
# o fim da sessão, e cada letra digitada fora de formulário provocava um
# rerun inteiro do app (com consulta ao banco) antes do clique em Entrar.
CHAVE_ULTIMO_USUARIO = "_login_ultimo_usuario"


def validar_entrada(usuario: str, senha: str) -> str | None:
    """Mensagem de erro para campo vazio, ANTES de qualquer rede."""
    if not (usuario or "").strip() and not senha:
        return "Informe usuário e senha."
    if not (usuario or "").strip():
        return "Informe o usuário."
    if not senha:
        return "Informe a senha."
    return None


def render_login() -> None:
    """Autenticação institucional sem cadastro ou recuperação fictícios."""

    def _conteudo() -> None:
        st.markdown('<p class="gc-login-module">GovDocs</p>',
                    unsafe_allow_html=True)
        st.subheader("Acesso ao sistema")
        aviso = st.session_state.pop(auth.CHAVE_AVISO_SESSAO, "")
        if aviso:
            st.info(aviso)
        # Formulário: um envio por clique ou Enter, nenhum rerun por tecla.
        with st.form("form_login", clear_on_submit=True, border=False):
            usuario = st.text_input(
                "Usuário",
                value=st.session_state.get(CHAVE_ULTIMO_USUARIO, ""),
                placeholder="Digite seu usuário",
                autocomplete="username",
            )
            senha = st.text_input(
                "Senha",
                type="password",
                placeholder="Digite sua senha",
                autocomplete="current-password",
            )
            enviado = st.form_submit_button(
                "Entrar", type="primary", use_container_width=True)

        if enviado:
            st.session_state[CHAVE_ULTIMO_USUARIO] = (usuario or "").strip()
            erro_local = validar_entrada(usuario, senha)
            if erro_local:
                st.error(erro_local, icon=None)
            else:
                try:
                    with st.spinner("Validando credenciais…"):
                        autenticado = auth.autenticar(usuario, senha)
                    auth.entrar(autenticado)
                    st.session_state.pop(CHAVE_ULTIMO_USUARIO, None)
                    st.rerun()
                except auth.ErroAuth as erro:
                    st.error(str(erro), icon=None)

        st.markdown(
            '<p class="gc-login-note">As contas de acesso são criadas pelo '
            'administrador.</p>',
            unsafe_allow_html=True,
        )

    _layout_porta_entrada(_conteudo)
