"""
GovDocs Wizard — Gerador de Documentos da Fase Preparatória
Lei nº 14.133/2021 (Nova Lei de Licitações e Contratos Administrativos)

Ponto de entrada da aplicação Streamlit. Roteia o usuário pelo fluxo:

    Formulário Matriz ➜ DFD ➜ ETP ➜ TR ➜ Minuta de Edital/Ata ➜ Download

COMO RODAR LOCALMENTE
---------------------
1. Crie e ative um ambiente virtual (recomendado):
       python -m venv .venv && source .venv/bin/activate    # Linux/macOS
       python -m venv .venv && .venv\\Scripts\\activate       # Windows

2. Instale as dependências:
       pip install -r requirements.txt

3. Configure a CHAVE DA API (uma das opções):
       a) Copie .streamlit/secrets.toml.example para .streamlit/secrets.toml
          e cole sua chave do Google AI Studio (https://aistudio.google.com/apikey);
       b) OU exporte a variável de ambiente:  export GOOGLE_API_KEY="sua-chave"
       c) OU cole a chave direto na barra lateral da aplicação.
       (Sem chave, ative o "Modo Demonstração" na barra lateral para testar.)

4. Execute:
       streamlit run app.py
   A aplicação abrirá em http://localhost:8501
"""

import streamlit as st

from src import state
from src.ui import biblioteca, components, steps

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
components.render_sidebar()
components.render_cabecalho()

# ---------------------------------------------------------------------------
# Navegação: Assistente (wizard) | Base de Conhecimento (RAG)
# ---------------------------------------------------------------------------
if st.session_state.get("pagina") == "Base de Conhecimento":
    biblioteca.render_biblioteca()
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
    # Só chega à tela de sucesso com os 4 documentos aprovados
    if len(st.session_state.aprovados) < 4:
        state.ir_para(0 if not st.session_state.dados else len(st.session_state.aprovados) + 1)
    else:
        steps.render_sucesso()
