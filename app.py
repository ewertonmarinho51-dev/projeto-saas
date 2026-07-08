"""
GovDocs Wizard — Gerador de Documentos da Fase Preparatória
Lei nº 14.133/2021 (Nova Lei de Licitações e Contratos Administrativos)

Ponto de entrada da aplicação Streamlit.

Controle de acesso:
  - Administrador: wizard + Base de Conhecimento + Administração
    (usuários, chaves de IA, identidade visual dos documentos)
  - Usuário: apenas o wizard de elaboração dos documentos
  - Sem Supabase configurado: MODO ABERTO local, sem login (dev/CI)

COMO RODAR LOCALMENTE
---------------------
1. python -m venv .venv && source .venv/bin/activate
2. pip install -r requirements.txt
3. Configure .streamlit/secrets.toml (copie de secrets.toml.example):
   SUPABASE_URL/SUPABASE_KEY habilitam login, persistência e RAG;
   as chaves de IA podem ser definidas pelo administrador no app.
4. streamlit run app.py       (abre em http://localhost:8501)
   No primeiro acesso com banco, o app pede a criação do administrador.
"""

import streamlit as st

from src import auth, state
from src.ui import admin, biblioteca, components, login, steps

# Configuração da página — deve ser a 1ª chamada Streamlit do script
st.set_page_config(
    page_title="GovDocs Wizard — Lei 14.133/2021",
    page_icon="🏛️",
    layout="wide",
    initial_sidebar_state="expanded",
)

# Estado persistente entre os passos (dados, documentos, aprovações)
state.inicializar()
components.aplicar_estilo()

# ---------------------------------------------------------------------------
# Porta de entrada: configuração necessária → login → app
# ---------------------------------------------------------------------------
if auth.precisa_configurar():
    components.render_cabecalho()
    login.render_configuracao_necessaria()
    st.stop()

if not auth.modo_aberto() and not auth.usuario_logado():
    components.render_cabecalho()
    try:
        existe_admin = auth.tem_admin()
    except auth.ErroAuth as erro:
        st.error(str(erro))
        st.info(
            "Se as tabelas ainda não existem, aplique as migrações em "
            "`supabase/migrations/` no SQL Editor do painel Supabase."
        )
        st.stop()
    if existe_admin:
        login.render_login()
    else:
        login.render_bootstrap_admin()
    st.stop()

components.render_sidebar()
components.render_cabecalho()

# ---------------------------------------------------------------------------
# Navegação por papel: admin vê Base de Conhecimento e Administração
# ---------------------------------------------------------------------------
pagina = st.session_state.get("pagina", "")
if auth.eh_admin() and pagina == "Base de Conhecimento":
    biblioteca.render_biblioteca()
    st.stop()
if auth.eh_admin() and pagina == "Administração":
    admin.render_admin()
    st.stop()

components.render_stepper(st.session_state.etapa)

# ---------------------------------------------------------------------------
# Roteamento do wizard
# ---------------------------------------------------------------------------
etapa = st.session_state.etapa

if etapa == 0:
    steps.render_formulario()
elif 1 <= etapa <= 4:
    # Proteção de sequência: não permite pular etapas sem aprovar as anteriores
    doc_key = state.doc_da_etapa(etapa)
    anterior = state.doc_da_etapa(etapa - 1) if etapa > 1 else None
    if not st.session_state.dados:
        st.warning("Preencha o Formulário Matriz antes de gerar documentos.")
        state.ir_para(0)
    elif anterior and anterior not in st.session_state.aprovados:
        st.warning(
            f"Aprove o {state.doc_da_etapa(etapa - 1).upper()} antes de avançar."
        )
        state.ir_para(etapa - 1)
    else:
        steps.render_etapa_documento(doc_key)
else:
    # Só chega à tela de conclusão com os 4 documentos aprovados
    if len(st.session_state.aprovados) < 4:
        state.ir_para(0 if not st.session_state.dados else len(st.session_state.aprovados) + 1)
    else:
        steps.render_sucesso()
