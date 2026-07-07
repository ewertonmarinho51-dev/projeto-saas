"""
Componentes visuais: CSS institucional, cabeçalho, stepper e barra lateral.

Linguagem visual (skills design-taste + design-minimalist, preset
setor público): monocromático quente, um único acento (#1B4F8A),
flat (sem gradientes/sombras), sem emojis, raios 8px (containers) e
6px (interativos), motion mínimo.
"""

import streamlit as st

from .. import auth, db, state
from ..config import APP_SUBTITULO, APP_TITULO, ETAPAS
from ..llm import motor_ativo

_CSS = """
<style>
:root {
    --azul: #1B4F8A;          /* acento único */
    --azul-escuro: #163F73;
    --azul-pale: #E8F0F9;     /* fundo de callout */
    --tinta: #2F3437;         /* texto principal (off-black) */
    --cinza: #787774;         /* texto secundário */
    --linha: #E7E6E3;         /* bordas 1px */
    --superficie: #FFFFFF;
    --canvas: #FBFBFA;
}

html, body, [class*="css"] {
    font-family: "SF Pro Display", "Segoe UI", "Helvetica Neue", Helvetica, Arial, sans-serif;
    -webkit-font-smoothing: antialiased;
    color: var(--tinta);
}

.block-container { padding-top: 1.6rem; max-width: 1040px; }

h1, h2, h3 { letter-spacing: -0.02em; color: var(--tinta); }

/* ---------- Cabeçalho institucional (flat, sem gradiente) ---------- */
.gd-header {
    background: var(--superficie);
    border: 1px solid var(--linha);
    border-radius: 8px;
    padding: 1.05rem 1.3rem;
    margin-bottom: 1.25rem;
    display: flex; align-items: center; gap: .85rem;
}
.gd-header-marca {
    width: 12px; height: 40px; border-radius: 3px;
    background: var(--azul); flex: none;
}
.gd-header h1 {
    margin: 0; font-size: 1.28rem; font-weight: 700; line-height: 1.2;
}
.gd-header p {
    margin: .15rem 0 0; font-size: .84rem; color: var(--cinza);
}

/* ---------- Stepper (flat, número + rótulo, conector fino) ---------- */
.gd-stepper {
    display: flex; gap: 0; margin-bottom: 1.4rem;
    border: 1px solid var(--linha); border-radius: 8px;
    background: var(--superficie); overflow: hidden;
}
.gd-step {
    flex: 1 1 0; display: flex; align-items: center; justify-content: center;
    gap: .45rem; padding: .62rem .4rem;
    font-size: .78rem; font-weight: 600; color: var(--cinza);
    border-right: 1px solid var(--linha); white-space: nowrap;
}
.gd-step:last-child { border-right: none; }
.gd-step-num {
    width: 1.35rem; height: 1.35rem; border-radius: 4px;
    display: inline-flex; align-items: center; justify-content: center;
    font-size: .72rem; font-weight: 700;
    border: 1px solid var(--linha); background: var(--canvas);
    color: var(--cinza); flex: none;
}
.gd-step.ativo { color: var(--tinta); background: var(--azul-pale); }
.gd-step.ativo .gd-step-num {
    background: var(--azul); border-color: var(--azul); color: #fff;
}
.gd-step.concluido { color: var(--azul); }
.gd-step.concluido .gd-step-num {
    background: var(--superficie); border-color: var(--azul); color: var(--azul);
}

/* ---------- Callout de base legal ---------- */
.gd-base-legal {
    background: var(--azul-pale);
    border: 1px solid #D2E2F2; border-left: 3px solid var(--azul);
    padding: .68rem 1rem; border-radius: 8px;
    font-size: .86rem; color: #24425F; margin-bottom: 1rem;
}

/* ---------- Interativos: raio 6px, feedback tátil sutil ---------- */
.stButton > button, .stDownloadButton > button, .stFormSubmitButton > button {
    border-radius: 6px !important;
    box-shadow: none !important;
    transition: background .15s ease, transform .1s ease;
}
.stButton > button:active, .stDownloadButton > button:active,
.stFormSubmitButton > button:active { transform: scale(0.98); }

.stTextInput input, .stNumberInput input, .stTextArea textarea,
.stSelectbox [data-baseweb="select"] > div {
    border-radius: 6px !important;
}

/* ---------- Superfícies ---------- */
[data-testid="stSidebar"] {
    background: var(--superficie);
    border-right: 1px solid var(--linha);
}
[data-testid="stExpander"] details {
    border: 1px solid var(--linha); border-radius: 8px;
}
hr { border-color: var(--linha); }
</style>
"""


def aplicar_estilo() -> None:
    st.markdown(_CSS, unsafe_allow_html=True)


def render_cabecalho() -> None:
    st.markdown(
        f"""<div class="gd-header">
            <div class="gd-header-marca"></div>
            <div>
                <h1>{APP_TITULO}</h1>
                <p>{APP_SUBTITULO}</p>
            </div>
        </div>""",
        unsafe_allow_html=True,
    )


def render_stepper(etapa_atual: int) -> None:
    """Barra de progresso do wizard: número + rótulo por etapa."""
    blocos = []
    for i, nome in enumerate(ETAPAS):
        classe = "ativo" if i == etapa_atual else "concluido" if i < etapa_atual else ""
        rotulo = nome.split(". ", 1)[-1]
        blocos.append(
            f'<div class="gd-step {classe}">'
            f'<span class="gd-step-num">{i + 1}</span>{rotulo}</div>'
        )
    st.markdown(
        f'<div class="gd-stepper">{"".join(blocos)}</div>', unsafe_allow_html=True
    )


def render_base_legal(texto: str) -> None:
    st.markdown(f'<div class="gd-base-legal">{texto}</div>', unsafe_allow_html=True)


def _render_processos_salvos() -> None:
    """Painel de processos persistidos no Supabase (retomar / excluir)."""
    st.markdown("### Processos salvos")
    if not db.disponivel():
        st.caption(
            "Configure SUPABASE_URL e SUPABASE_KEY em .streamlit/secrets.toml "
            "para salvar o andamento e retomá-lo depois (banco Supabase)."
        )
        return

    if st.session_state.processo_id:
        st.caption(f"Processo atual salvo (id: {st.session_state.processo_id[:8]}…)")

    usuario = auth.usuario_logado()
    filtro = None if auth.eh_admin() else (usuario or {}).get("id")
    try:
        processos = db.listar_processos(usuario_id=filtro)
    except db.ErroBanco as erro:
        st.warning(str(erro))
        return

    if not processos:
        st.caption("Nenhum processo salvo ainda. O andamento é salvo automaticamente.")
        return

    rotulos = {db.rotulo_processo(p): p for p in processos}
    escolha = st.selectbox(
        "Retomar processo",
        list(rotulos),
        index=None,
        placeholder="Selecione um processo…",
        help="O andamento é salvo automaticamente a cada etapa aprovada.",
    )
    col_abrir, col_excluir = st.columns(2)
    if col_abrir.button("Abrir", use_container_width=True, disabled=not escolha):
        try:
            proc = db.carregar_processo(rotulos[escolha]["id"])
            if proc:
                state.carregar_processo_salvo(proc)
            else:
                st.warning("Processo não encontrado. Pode ter sido excluído.")
        except db.ErroBanco as erro:
            st.warning(str(erro))
    if col_excluir.button("Excluir", use_container_width=True, disabled=not escolha):
        try:
            db.excluir_processo(rotulos[escolha]["id"])
            if st.session_state.processo_id == rotulos[escolha]["id"]:
                st.session_state.processo_id = None
            st.rerun()
        except db.ErroBanco as erro:
            st.warning(str(erro))


def render_sidebar() -> None:
    with st.sidebar:
        usuario = auth.usuario_logado()
        if auth.eh_admin():
            st.radio(
                "Navegação",
                options=[
                    "Assistente de Documentos",
                    "Base de Conhecimento",
                    "Administração",
                ],
                key="pagina",
                label_visibility="collapsed",
            )
            st.divider()

        if usuario:
            papel = "Administrador" if usuario["papel"] == "admin" else "Usuário"
            st.markdown(f"**{usuario['nome']}**  \n{papel} · `{usuario['login']}`")
            if st.button("Sair", use_container_width=True):
                auth.sair()
                st.rerun()
            st.divider()

        motor = motor_ativo()
        if motor == "openai":
            st.caption("Motor de IA: OpenAI (principal)")
        elif motor == "gemini":
            st.caption("Motor de IA: Gemini (fallback)")
        else:
            st.caption("Motor de IA: não configurado (Modo Demonstração)")

        if auth.eh_admin():
            st.toggle(
                "Modo Demonstração (sem IA)",
                key="modo_demo",
                help=(
                    "Gera minutas-esqueleto offline, sem consumir a API. Útil "
                    "para conhecer o fluxo completo antes de configurar a chave."
                ),
            )

        st.divider()
        _render_processos_salvos()

        st.divider()
        st.markdown("### Sobre")
        st.caption(
            "Assistente passo a passo para elaboração do DFD, ETP, TR e "
            "Minuta de Edital/Ata (fase preparatória, art. 12 e seguintes "
            "da Lei nº 14.133/2021). Todo texto gerado pela IA é um rascunho "
            "que exige revisão e aprovação humana antes do uso oficial."
        )
