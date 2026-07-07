"""
Página "Administração" (exclusiva do papel admin):
  - Usuários: criar contas, alterar papel, ativar/desativar, trocar senha
  - Chaves de IA: OPENAI_API_KEY / GOOGLE_API_KEY e modelos
  - Identidade visual: cabeçalho, rodapé e marca d'água por órgão
"""

import streamlit as st

from .. import auth, db
from ..llm import motor_ativo


def render_admin() -> None:
    st.subheader("Administração")
    aba_usuarios, aba_chaves, aba_identidade = st.tabs(
        ["Usuários", "Chaves de IA", "Identidade visual"]
    )
    with aba_usuarios:
        _render_usuarios()
    with aba_chaves:
        _render_chaves()
    with aba_identidade:
        _render_identidade()


# ---------------------------------------------------------------------------
# Usuários
# ---------------------------------------------------------------------------
def _render_usuarios() -> None:
    with st.form("form_novo_usuario", clear_on_submit=True):
        st.markdown("##### Nova conta")
        col1, col2 = st.columns(2)
        nome = col1.text_input("Nome completo")
        login = col2.text_input("Login")
        col3, col4 = st.columns(2)
        senha = col3.text_input("Senha inicial", type="password",
                                help="Mínimo de 8 caracteres.")
        papel = col4.selectbox(
            "Papel", ["usuario", "admin"],
            format_func=lambda p: "Usuário (elabora documentos)"
            if p == "usuario" else "Administrador",
        )
        if st.form_submit_button("Criar conta", type="primary",
                                 use_container_width=True):
            try:
                auth.criar_usuario(nome, login, senha, papel)
                st.success(f"Conta '{login}' criada.")
            except auth.ErroAuth as erro:
                st.error(str(erro))

    st.divider()
    st.markdown("##### Contas cadastradas")
    try:
        usuarios = auth.listar_usuarios()
    except auth.ErroAuth as erro:
        st.error(str(erro))
        return

    eu = (auth.usuario_logado() or {}).get("id")
    for u in usuarios:
        col_info, col_papel, col_ativo, col_senha = st.columns([3, 2, 1.4, 1.6])
        situacao = "ativa" if u["ativo"] else "desativada"
        col_info.markdown(f"**{u['nome']}**  \n`{u['login']}` · conta {situacao}")
        novo_papel = col_papel.selectbox(
            "Papel", ["usuario", "admin"],
            index=0 if u["papel"] == "usuario" else 1,
            key=f"papel_{u['id']}", label_visibility="collapsed",
            format_func=lambda p: "Usuário" if p == "usuario" else "Administrador",
            disabled=u["id"] == eu,
        )
        if novo_papel != u["papel"]:
            try:
                auth.atualizar_usuario(u["id"], papel=novo_papel)
                st.rerun()
            except auth.ErroAuth as erro:
                st.error(str(erro))
        rotulo_ativo = "Desativar" if u["ativo"] else "Reativar"
        if col_ativo.button(rotulo_ativo, key=f"ativo_{u['id']}",
                            use_container_width=True, disabled=u["id"] == eu):
            try:
                auth.atualizar_usuario(u["id"], ativo=not u["ativo"])
                st.rerun()
            except auth.ErroAuth as erro:
                st.error(str(erro))
        with col_senha.popover("Trocar senha", use_container_width=True):
            nova = st.text_input("Nova senha", type="password",
                                 key=f"senha_{u['id']}")
            if st.button("Salvar", key=f"salva_senha_{u['id']}",
                         type="primary"):
                try:
                    auth.atualizar_usuario(u["id"], senha=nova)
                    st.success("Senha alterada.")
                except auth.ErroAuth as erro:
                    st.error(str(erro))


# ---------------------------------------------------------------------------
# Chaves de IA
# ---------------------------------------------------------------------------
def _render_chaves() -> None:
    st.caption(
        "As chaves ficam no banco e valem para todos os usuários. "
        "Campos vazios mantêm o valor atual; para remover, salve um espaço."
    )
    motor = motor_ativo()
    if motor:
        st.success(f"Motor ativo: {'OpenAI (principal)' if motor == 'openai' else 'Gemini (fallback)'}")
    else:
        st.warning("Nenhuma chave configurada. A geração usará o Modo Demonstração.")

    with st.form("form_chaves"):
        openai_key = st.text_input(
            "OPENAI_API_KEY (motor principal)", type="password",
            placeholder="sk-..." if not db.obter_config("OPENAI_API_KEY")
            else "definida (oculta)",
        )
        openai_model = st.text_input(
            "OPENAI_MODEL (opcional)", value=db.obter_config("OPENAI_MODEL"),
            placeholder="padrão: gpt-5-mini",
        )
        gemini_key = st.text_input(
            "GOOGLE_API_KEY (fallback, opcional)", type="password",
            placeholder="definida (oculta)" if db.obter_config("GOOGLE_API_KEY")
            else "",
        )
        gemini_model = st.text_input(
            "GEMINI_MODEL (opcional)", value=db.obter_config("GEMINI_MODEL"),
            placeholder="padrão: gemini-2.5-flash",
        )
        if st.form_submit_button("Salvar chaves", type="primary",
                                 use_container_width=True):
            try:
                for chave, valor in [
                    ("OPENAI_API_KEY", openai_key),
                    ("OPENAI_MODEL", openai_model),
                    ("GOOGLE_API_KEY", gemini_key),
                    ("GEMINI_MODEL", gemini_model),
                ]:
                    if valor.strip() or chave.endswith("_MODEL"):
                        db.salvar_config(chave, valor)
                st.success("Configurações salvas.")
                st.rerun()
            except db.ErroBanco as erro:
                st.error(str(erro))


# ---------------------------------------------------------------------------
# Identidade visual por órgão
# ---------------------------------------------------------------------------
def _render_identidade() -> None:
    st.caption(
        "Cabeçalho e rodapé aparecem em todas as páginas dos documentos "
        "exportados (PDF e DOCX); a marca d'água diagonal é aplicada no PDF. "
        "A identidade padrão vem pré-selecionada na tela de download."
    )
    with st.form("form_orgao", clear_on_submit=True):
        st.markdown("##### Nova identidade")
        orgao = st.text_input("Órgão", placeholder="Ex.: Prefeitura Municipal de Exemplo")
        cabecalho = st.text_input(
            "Cabeçalho", placeholder="Ex.: PREFEITURA MUNICIPAL DE EXEMPLO · SECRETARIA DE ADMINISTRAÇÃO"
        )
        rodape = st.text_input(
            "Rodapé", placeholder="Ex.: Rua das Flores, 100, Centro · (11) 4002-8922 · compras@exemplo.gov.br"
        )
        marca = st.text_input(
            "Marca d'água (PDF)", placeholder="Ex.: MINUTA ou nome do órgão"
        )
        padrao = st.checkbox("Definir como identidade padrão")
        if st.form_submit_button("Salvar identidade", type="primary",
                                 use_container_width=True):
            if not orgao.strip():
                st.error("Informe o nome do órgão.")
            else:
                try:
                    db.salvar_orgao({
                        "orgao": orgao.strip(), "cabecalho": cabecalho.strip(),
                        "rodape": rodape.strip(), "marca_dagua": marca.strip(),
                        "padrao": padrao,
                    })
                    st.success("Identidade salva.")
                    st.rerun()
                except db.ErroBanco as erro:
                    st.error(str(erro))

    st.divider()
    st.markdown("##### Identidades cadastradas")
    try:
        orgaos = db.listar_orgaos()
    except db.ErroBanco as erro:
        st.error(str(erro))
        return
    if not orgaos:
        st.caption("Nenhuma identidade cadastrada.")
    for o in orgaos:
        col_info, col_padrao, col_acao = st.columns([4, 1.4, 1.2])
        etiqueta = " (padrão)" if o["padrao"] else ""
        col_info.markdown(
            f"**{o['orgao']}{etiqueta}**  \n"
            f"{o['cabecalho'] or 'sem cabeçalho'}  \n"
            f"{o['rodape'] or 'sem rodapé'} · marca: {o['marca_dagua'] or 'nenhuma'}"
        )
        if not o["padrao"] and col_padrao.button(
            "Tornar padrão", key=f"padrao_{o['id']}", use_container_width=True
        ):
            try:
                db.salvar_orgao({"padrao": True}, o["id"])
                st.rerun()
            except db.ErroBanco as erro:
                st.error(str(erro))
        if col_acao.button("Excluir", key=f"del_orgao_{o['id']}",
                           use_container_width=True):
            try:
                db.excluir_orgao(o["id"])
                st.rerun()
            except db.ErroBanco as erro:
                st.error(str(erro))
