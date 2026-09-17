"""Preview local sintético: sem Supabase, credenciais ou chamadas de modelo.

Executar apenas com streamlit run tests/manual_preview.py --server.address 127.0.0.1.
Não é entrypoint de produção; mocks existem somente neste processo de teste.
"""
import runpy
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import streamlit as st
from src import auth, db, state
from src.ui import steps
from src.llm import gerar_documento as gerar_original
import time

db.disponivel = lambda: False
db.em_manutencao = lambda: False
db.flag_ativa = lambda key: key in {"govbot", "govbot_alertas", "editor_rico", "mapa_riscos", "loading_overlay"}
auth.modo_aberto = lambda: True
auth.precisa_configurar = lambda: False
auth.eh_admin = lambda: False

def banco_proibido(*args, **kwargs):
    raise AssertionError("O preview sintético não pode acessar banco")
db._cliente = banco_proibido

def gerar_preview(doc, dados, contexto, **kwargs):
    progresso = kwargs.get("progresso")
    if progresso:
        progresso("GERANDO")
    time.sleep(3)  # demora sintética para inspecionar o bloqueio da interface
    if st.session_state.get("_preview_falhar_geracao"):
        raise RuntimeError("Falha sintética do preview")
    return gerar_original(doc, dados, contexto, **kwargs)
steps.gerar_documento = gerar_preview

state.inicializar()
if not st.session_state.get("_preview_inicializado"):
    st.session_state.update({"_preview_inicializado": True, "modo_demo": True,
        "dados": {"orgao": "Órgão de demonstração", "objeto": "Aquisição de papel A4",
                  "_fluxo_mapa_riscos": True},
        "documentos": {"dfd": "# DFD\n\nDemanda de papel para expediente.",
            "etp": "## 1. Necessidade\n\n**Aquisição de papel** para *atividades administrativas*.\n\n1. Fornecimento\n    - Embalagens íntegras\n\n| Id | Requisito |\n|---|---|\n| 1 | Papel A4 |"},
        "aprovados": {"dfd"}, "etapa": 2})
runpy.run_path(str(ROOT / "app.py"), run_name="__main__")
def configurar_falha():
    st.session_state["_preview_falhar_geracao"] = st.session_state["_preview_falha"]

st.checkbox("Simular falha de geração (somente preview)", key="_preview_falha",
            value=st.session_state.get("_preview_falhar_geracao", False),
            on_change=configurar_falha)
