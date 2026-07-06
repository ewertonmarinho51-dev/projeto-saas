"""
Componentes visuais reutilizáveis: CSS corporativo, cabeçalho,
indicador de passos (stepper) e barra lateral.
"""

import streamlit as st

from ..config import APP_SUBTITULO, APP_TITULO, ETAPAS
from ..llm import obter_api_key

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


def render_sidebar() -> None:
    with st.sidebar:
        st.markdown("### ⚙️ Configuração da IA")
        st.text_input(
            "Chave da API (Google AI Studio)",
            type="password",
            key="api_key_manual",
            help=(
                "Obtenha gratuitamente em https://aistudio.google.com/apikey. "
                "Alternativas: arquivo .streamlit/secrets.toml ou variável de "
                "ambiente GOOGLE_API_KEY."
            ),
        )
        if obter_api_key():
            st.success("Chave de API detectada.", icon="🔑")
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
        st.markdown("### 📄 Sobre")
        st.caption(
            "Assistente passo a passo para elaboração do DFD, ETP, TR e "
            "Minuta de Edital/Ata (fase preparatória — art. 12 e seguintes "
            "da Lei nº 14.133/2021). Todo texto gerado pela IA é um rascunho "
            "que exige revisão e aprovação humana antes do uso oficial."
        )
