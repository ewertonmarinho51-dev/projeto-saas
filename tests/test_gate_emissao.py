"""
Testes do gate técnico de emissão (Etapa 7): documento aprovado libera
(T14), não aprovado não emite (T15), flag OFF preserva o comportamento
anterior (T20) e o bundle corrigido continua renderizando DOCX/PDF
válidos (T18).
"""

import io
import zipfile
from pathlib import Path

import streamlit as st
from streamlit.testing.v1 import AppTest

from src import blocos, ciclo, db, export
from src.ui import revisao

APP = str(Path(__file__).resolve().parent.parent / "app.py")

DOCS = {"dfd": "## 1. OBJETO\n\nContrato de 12 (doze) meses.\n"}


def _evidencia_aprovada(docs):
    st.session_state["_ciclo_resultado"] = {
        "hash": blocos.hash_bundle(docs),
        "resultado": {"status": "APPROVED"},
    }


# ---------------------------------------------------------------------------
# unidade: T14 / T15 / T20
# ---------------------------------------------------------------------------
def test_aprovado_para_a_versao_atual_libera(monkeypatch):
    monkeypatch.setattr(revisao.db, "flag_ativa",
                        lambda n: n == revisao.FLAG_GATE)
    _evidencia_aprovada(DOCS)
    liberada, motivo = revisao.emissao_liberada(DOCS)
    assert liberada and motivo == ""


def test_sem_aprovacao_nao_emite(monkeypatch):
    monkeypatch.setattr(revisao.db, "flag_ativa",
                        lambda n: n == revisao.FLAG_GATE)
    st.session_state.pop("_ciclo_resultado", None)
    liberada, motivo = revisao.emissao_liberada(DOCS)
    assert not liberada and "gate técnico" in motivo


def test_edicao_apos_aprovacao_invalida_o_gate(monkeypatch):
    monkeypatch.setattr(revisao.db, "flag_ativa",
                        lambda n: n == revisao.FLAG_GATE)
    _evidencia_aprovada(DOCS)
    editados = {"dfd": DOCS["dfd"].replace("12 (doze)", "36 (trinta e seis)")}
    liberada, _ = revisao.emissao_liberada(editados)
    assert not liberada  # hash mudou: exige nova aprovação


def test_flag_desligada_nao_muda_nada(monkeypatch):
    monkeypatch.setattr(revisao.db, "flag_ativa", lambda n: False)
    st.session_state.pop("_ciclo_resultado", None)
    assert revisao.emissao_liberada(DOCS) == (True, "")


# ---------------------------------------------------------------------------
# T15 na tela real: ciclo bloqueado + gate ligado = zero downloads
# ---------------------------------------------------------------------------
def test_tela_sem_aprovacao_nao_mostra_downloads(monkeypatch):
    bundle = {
        "dfd": "## 1. OBJETO\n\nplaceholder\n",
        "etp": "## 1. OBJETO\n\nEstudo.\n",
        "tr": "## 1. OBJETO\n\nTermo.\n",
        "edital": "## 1. OBJETO\n\nEdital.\n",
    }
    resultado = {
        "status": "BLOCKED_MAX_CYCLES", "documentos": dict(bundle),
        "versao": 1, "ciclos": 3,
        "relatorios": [{"summary": "s", "findings": []}],
        "planos": [], "diffs": [], "eventos": [], "campos_requeridos": [],
    }
    monkeypatch.setattr(
        db, "flag_ativa",
        lambda n: n in (revisao.FLAG_TELA, revisao.FLAG_GATE,
                        "correcao_automatica"))
    monkeypatch.setattr(ciclo, "executar_com_persistencia",
                        lambda *a, **k: resultado)
    import os

    os.environ["GOVDOCS_MODO_ABERTO"] = "1"
    at = AppTest.from_file(APP, default_timeout=60)
    at.secrets["SUPABASE_URL"] = ""
    at.secrets["SUPABASE_KEY"] = ""
    at.session_state["etapa"] = 5
    at.session_state["dados"] = {"orgao": "Prefeitura"}
    at.session_state["documentos"] = dict(bundle)
    at.session_state["aprovados"] = {"dfd", "etp", "tr", "edital"}
    at.run()
    assert not at.exception
    assert not [b for b in at.get("download_button")]
    erros = " ".join(e.value for e in at.error)
    assert "limite seguro de ciclos" in erros


# ---------------------------------------------------------------------------
# T18: bundle corrigido continua exportando DOCX/PDF válidos
# ---------------------------------------------------------------------------
def test_bundle_corrigido_renderiza_docx_e_pdf_validos():
    docs = {"dfd": "## 1. OBJETO\n\nContrato de 12 (doze) meses.\n\n"
                   "## 2. VALOR\n\nR$ 100,00 conforme planilha.\n"}
    docx = export.gerar_docx_consolidado(docs, None)
    with zipfile.ZipFile(io.BytesIO(docx)) as pacote:
        xml = pacote.read("word/document.xml").decode("utf-8")
    assert "12 (doze) meses" in xml

    pdf = export.gerar_pdf_consolidado(docs, None)
    assert pdf[:5] == b"%PDF-" and len(pdf) > 1000
