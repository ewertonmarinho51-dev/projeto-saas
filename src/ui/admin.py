"""
Página "Administração" (exclusiva do papel admin):
  - Usuários: criar contas, alterar papel, ativar/desativar, trocar senha
  - Chaves de IA: OPENAI_API_KEY / GOOGLE_API_KEY e modelos
  - Identidade visual: cabeçalho, rodapé e marca d'água por órgão
"""

import streamlit as st

from .. import auth, branding, db, llm
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

    # De onde vem cada chave ativa — o painel tem prioridade sobre o resto,
    # então uma chave antiga salva aqui sobrepõe a nova do secrets.toml.
    origem_openai = llm.origem_chave("OPENAI_API_KEY", "openai_key_manual")
    origem_gemini = llm.origem_chave("GOOGLE_API_KEY", "api_key_manual")
    st.caption(
        f"Chave OpenAI em uso: **{origem_openai or 'não configurada'}** · "
        f"Chave Gemini em uso: **{origem_gemini or 'não configurada'}**. "
        "Prioridade: painel do administrador > barra lateral > secrets.toml > "
        "variável de ambiente."
    )

    with st.form("form_chaves"):
        openai_key = st.text_input(
            "OPENAI_API_KEY (motor principal)", type="password",
            placeholder="sk-..." if not db.obter_config("OPENAI_API_KEY")
            else "definida (oculta)",
        )
        openai_model = st.text_input(
            "OPENAI_MODEL (opcional)", value=db.obter_config("OPENAI_MODEL"),
            placeholder="padrão: gpt-5-mini (cai p/ gpt-4o-mini se indisponível)",
        )
        gemini_key = st.text_input(
            "GOOGLE_API_KEY (fallback, opcional)", type="password",
            placeholder="definida (oculta)" if db.obter_config("GOOGLE_API_KEY")
            else "",
        )
        gemini_model = st.text_input(
            "GEMINI_MODEL (opcional)", value=db.obter_config("GEMINI_MODEL"),
            placeholder="padrão: gemini-2.5-flash (cai p/ gemini-1.5-flash se indisponível)",
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

    st.divider()
    st.markdown("##### Testar conexão")
    st.caption(
        "Faz uma chamada mínima a cada motor e mostra o erro técnico exato "
        "(chave, modelo ou cota). Se o modelo configurado não existir na sua "
        "conta, o sistema tenta modelos alternativos automaticamente."
    )
    col_o, col_g = st.columns(2)
    if col_o.button("Testar OpenAI", use_container_width=True):
        with st.spinner("Chamando a OpenAI…"):
            ok, msg = llm.testar_conexao("openai")
        (st.success if ok else st.error)(msg)
    if col_g.button("Testar Gemini", use_container_width=True):
        with st.spinner("Chamando o Gemini…"):
            ok, msg = llm.testar_conexao("gemini")
        (st.success if ok else st.error)(msg)


# ---------------------------------------------------------------------------
# Identidade visual por órgão
# ---------------------------------------------------------------------------
def _render_identidade() -> None:
    st.caption(
        "Cadastre a identidade por captura de imagem (recomendado) ou por "
        "texto. As imagens de cabeçalho e rodapé são carimbadas na mesma "
        "posição relativa dos documentos gerados (PDF e DOCX); a marca "
        "d'água é aplicada translúcida no PDF."
    )
    aba_imagem, aba_texto = st.tabs(
        ["Capturar de um modelo (PDF/DOCX)", "Definir por texto"]
    )
    with aba_imagem:
        _render_identidade_imagem()
    with aba_texto:
        _render_identidade_texto()

    _render_identidades_cadastradas()


def _render_identidade_imagem() -> None:
    modelo = st.file_uploader(
        "Documento-modelo do órgão (PDF ou DOCX)",
        type=["pdf", "docx"],
        help="A 1ª página é usada para capturar cabeçalho, rodapé e marca d'água.",
    )
    if not modelo:
        st.caption("Envie um documento oficial para capturar a identidade visual.")
        return

    # Renderiza uma vez por arquivo (cacheado por conteúdo) para as prévias
    dados = modelo.getvalue()
    chave = f"modelo_{hash(dados)}"
    if st.session_state.get("_modelo_chave") != chave:
        try:
            img = branding.renderizar_modelo(modelo.name, dados)
        except branding.ErroBranding as erro:
            st.error(str(erro))
            return
        st.session_state["_modelo_chave"] = chave
        st.session_state["_modelo_img"] = img
    img = st.session_state.get("_modelo_img")
    if img is None:
        return

    col_ctrl, col_prev = st.columns([1, 1])
    with col_ctrl:
        cab_pct = st.slider("Altura do cabeçalho (% da página)", 3, 40, 14)
        rod_pct = st.slider("Altura do rodapé (% da página)", 3, 40, 10)
        usar_marca = st.checkbox("Capturar marca d'água (miolo translúcido)", value=False)
    with col_prev:
        st.image(img, caption="Modelo (1ª página)", use_container_width=True)

    png_cab = branding.recortar_cabecalho(img, cab_pct)
    png_rod = branding.recortar_rodape(img, rod_pct)
    png_marca = branding.recortar_marca_dagua(img) if usar_marca else b""

    st.markdown("**Prévia do que será carimbado:**")
    st.image(png_cab, caption="Cabeçalho", use_container_width=True)
    st.image(png_rod, caption="Rodapé", use_container_width=True)

    with st.form("form_orgao_img", clear_on_submit=False):
        orgao = st.text_input("Órgão", placeholder="Ex.: Prefeitura Municipal de Exemplo")
        padrao = st.checkbox("Definir como identidade padrão")
        if st.form_submit_button("Salvar identidade (imagem)", type="primary",
                                 use_container_width=True):
            if not orgao.strip():
                st.error("Informe o nome do órgão.")
            else:
                try:
                    db.salvar_orgao({
                        "orgao": orgao.strip(),
                        "cabecalho_img": branding.para_base64(png_cab),
                        "rodape_img": branding.para_base64(png_rod),
                        "marca_img": branding.para_base64(png_marca) if png_marca else "",
                        "cabecalho_pct": float(cab_pct),
                        "rodape_pct": float(rod_pct),
                        "padrao": padrao,
                    })
                    st.success("Identidade (imagem) salva.")
                    st.session_state.pop("_modelo_chave", None)
                    st.rerun()
                except db.ErroBanco as erro:
                    st.error(str(erro))


def _render_identidade_texto() -> None:
    with st.form("form_orgao_txt", clear_on_submit=True):
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
        padrao = st.checkbox("Definir como identidade padrão", key="padrao_txt")
        if st.form_submit_button("Salvar identidade (texto)", type="primary",
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


def _render_identidades_cadastradas() -> None:
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
        tem_img = bool(o.get("cabecalho_img") or o.get("rodape_img"))
        if tem_img:
            descricao = "Identidade por imagem (capturada de modelo)"
        else:
            descricao = (
                f"{o.get('cabecalho') or 'sem cabeçalho'}  \n"
                f"{o.get('rodape') or 'sem rodapé'} · "
                f"marca: {o.get('marca_dagua') or 'nenhuma'}"
            )
        col_info.markdown(f"**{o['orgao']}{etiqueta}**  \n{descricao}")
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
