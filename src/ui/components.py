"""
Componentes visuais reutilizáveis: CSS corporativo, cabeçalho,
indicador de passos (stepper) e barra lateral.
"""

import streamlit as st

from .. import db, state
from ..config import APP_SUBTITULO, APP_TITULO, ETAPAS
from ..llm import motor_ativo, obter_api_key

_CSS = """
<style>
/* Aparência corporativa/governamental */
.block-container { padding-top: 1.5rem; max-width: 1100px; }

.gd-header {
    background: linear-gradient(90deg, #12365f 0%, #1b4f8a 100%);
    color: #ffffff; padding: 1.1rem 1.4rem; border-radius: 10px;
    margin-bottom: 1.2rem;
}
.gd-header h1 { margin: 0; font-size: 1.45rem; color: #ffffff; }
.gd-header p  { margin: .25rem 0 0; font-size: .9rem; color: #cfe0f3; }

/* Stepper */
.gd-stepper { display: flex; gap: .4rem; margin-bottom: 1.4rem; flex-wrap: wrap; }
.gd-step {
    flex: 1 1 130px; text-align: center; font-size: .78rem; font-weight: 600;
    padding: .55rem .3rem; border-radius: 8px; border: 1px solid #d5dfe9;
    background: #f0f4f8; color: #6b7c8f; white-space: nowrap;
}
.gd-step.ativo     { background: #1b4f8a; border-color: #1b4f8a; color: #fff; }
.gd-step.concluido { background: #e6f2ea; border-color: #bcd9c6; color: #1e6b3a; }

.gd-base-legal {
    background: #eef4fb; border-left: 4px solid #1b4f8a;
    padding: .7rem 1rem; border-radius: 6px; font-size: .88rem;
    margin-bottom: 1rem; color: #24425f;
}
</style>
"""


def aplicar_estilo() -> None:
    st.markdown(_CSS, unsafe_allow_html=True)


def render_cabecalho() -> None:
    st.markdown(
        f"""<div class="gd-header">
            <h1>🏛️ {APP_TITULO}</h1>
            <p>{APP_SUBTITULO}</p>
        </div>""",
        unsafe_allow_html=True,
    )


def render_stepper(etapa_atual: int) -> None:
    """Barra horizontal com o progresso do wizard."""
    blocos = []
    for i, nome in enumerate(ETAPAS):
        classe = (
            "ativo" if i == etapa_atual else "concluido" if i < etapa_atual else ""
        )
        icone = "✓ " if i < etapa_atual else ""
        blocos.append(f'<div class="gd-step {classe}">{icone}{nome}</div>')
    st.markdown(
        f'<div class="gd-stepper">{"".join(blocos)}</div>', unsafe_allow_html=True
    )


def render_base_legal(texto: str) -> None:
    st.markdown(f'<div class="gd-base-legal">⚖️ {texto}</div>', unsafe_allow_html=True)


def _render_processos_salvos() -> None:
    """Painel de processos persistidos no Supabase (retomar / excluir)."""
    st.markdown("### 💾 Processos Salvos")
    if not db.disponivel():
        st.caption(
            "Configure SUPABASE_URL e SUPABASE_KEY em .streamlit/secrets.toml "
            "para salvar o andamento e retomá-lo depois (banco Supabase)."
        )
        return

    if st.session_state.processo_id:
        st.caption(f"Processo atual salvo (id: {st.session_state.processo_id[:8]}…)")

    try:
        processos = db.listar_processos()
    except db.ErroBanco as erro:
        st.warning(str(erro), icon="💾")
        return

    if not processos:
        st.caption("Nenhum processo salvo ainda — o andamento é salvo automaticamente.")
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
    if col_abrir.button("📂 Abrir", use_container_width=True, disabled=not escolha):
        try:
            proc = db.carregar_processo(rotulos[escolha]["id"])
            if proc:
                state.carregar_processo_salvo(proc)
            else:
                st.warning("Processo não encontrado — pode ter sido excluído.")
        except db.ErroBanco as erro:
            st.warning(str(erro), icon="💾")
    if col_excluir.button("🗑️ Excluir", use_container_width=True, disabled=not escolha):
        try:
            db.excluir_processo(rotulos[escolha]["id"])
            if st.session_state.processo_id == rotulos[escolha]["id"]:
                st.session_state.processo_id = None
            st.rerun()
        except db.ErroBanco as erro:
            st.warning(str(erro), icon="💾")


def render_sidebar() -> None:
    with st.sidebar:
        st.radio(
            "Navegação",
            options=["🧭 Assistente de Documentos", "📚 Base de Conhecimento"],
            key="pagina",
            label_visibility="collapsed",
        )
        st.divider()
        st.markdown("### ⚙️ Configuração da IA")
        st.text_input(
            "Chave OpenAI — motor principal",
            type="password",
            key="openai_key_manual",
            help=(
                "Chave sk-... da OpenAI (https://platform.openai.com/api-keys). "
                "Alternativas: OPENAI_API_KEY em .streamlit/secrets.toml ou no "
                "ambiente. Modelo padrão: gpt-5-mini (ajuste em OPENAI_MODEL)."
            ),
        )
        st.text_input(
            "Chave Google Gemini — fallback",
            type="password",
            key="api_key_manual",
            help=(
                "Opcional: usada se a OpenAI falhar e nos embeddings quando "
                "não houver chave OpenAI. GOOGLE_API_KEY em secrets/ambiente."
            ),
        )
        motor = motor_ativo()
        if motor == "openai":
            st.success("Motor ativo: OpenAI (principal)", icon="🔑")
            if obter_api_key():
                st.caption("Fallback Gemini configurado. ✔")
        elif motor == "gemini":
            st.info("Motor ativo: Gemini (fallback) — sem chave OpenAI.", icon="🔑")
        else:
            st.warning("Sem chave de API configurada.", icon="⚠️")

        st.toggle(
            "Modo Demonstração (sem IA)",
            key="modo_demo",
            help=(
                "Gera minutas-esqueleto offline, sem consumir a API — útil "
                "para conhecer o fluxo completo antes de configurar a chave."
            ),
        )

        st.divider()
        _render_processos_salvos()

        st.divider()
        st.markdown("### 📄 Sobre")
        st.caption(
            "Assistente passo a passo para elaboração do DFD, ETP, TR e "
            "Minuta de Edital/Ata (fase preparatória — art. 12 e seguintes "
            "da Lei nº 14.133/2021). Todo texto gerado pela IA é um rascunho "
            "que exige revisão e aprovação humana antes do uso oficial."
        )
