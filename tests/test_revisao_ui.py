"""
Testes da tela de correção automática (Etapa 6): substituição pontual
de dado ausente, as 5 etapas na ordem do pacote, flag OFF preservando a
tela antiga e o fluxo aprovado liberando a emissão com o bundle
corrigido.
"""

from pathlib import Path

import streamlit as st
from streamlit.testing.v1 import AppTest

from src import ciclo, db
from src.ui import revisao

APP = str(Path(__file__).resolve().parent.parent / "app.py")


# ---------------------------------------------------------------------------
# helpers puros
# ---------------------------------------------------------------------------
def test_aplicar_dado_pontual_substitui_somente_o_marcador():
    docs = {
        "dfd": "Prazo: [PREENCHER: prazo de vigência]. Valor: R$ 100,00.",
        "etp": "Outro doc com [PREENCHER: prazo de vigência].",
    }
    novos = revisao.aplicar_dado_pontual(
        docs, "dfd", "prazo de vigência", "12 meses")
    assert novos["dfd"] == "Prazo: 12 meses. Valor: R$ 100,00."
    assert novos["etp"] == docs["etp"]  # outro documento intocado
    assert docs["dfd"].startswith("Prazo: [PREENCHER")  # original intocado


def test_etapas_da_tela_seguem_o_pacote():
    assert [rotulo for _, rotulo in revisao.ETAPAS] == [
        "Analisando os documentos",
        "Preparando as correções",
        "Corrigindo os pontos identificados",
        "Validando novamente",
        "Preparando os arquivos finais",
    ]
    assert [etapa for etapa, _ in revisao.ETAPAS] == list(ciclo.ETAPAS_UI)


def test_flag_desligada_devolve_none_sem_rodar_o_ciclo(monkeypatch):
    monkeypatch.setattr(revisao.db, "flag_ativa", lambda n: False)

    def explode(*_a, **_k):
        raise AssertionError("flag OFF não pode executar o ciclo")

    monkeypatch.setattr(revisao, "_executar", explode)
    st.session_state["documentos"] = {"dfd": "## 1. X\n\ntexto\n"}
    assert revisao.render_correcao_automatica() is None


def test_saida_manual_tem_prioridade_sobre_a_flag(monkeypatch):
    monkeypatch.setattr(revisao.db, "flag_ativa", lambda n: True)
    st.session_state["_ciclo_manual"] = True
    try:
        assert revisao.render_correcao_automatica() is None
    finally:
        st.session_state.pop("_ciclo_manual", None)


# ---------------------------------------------------------------------------
# fluxo completo na tela final (AppTest)
# ---------------------------------------------------------------------------
DOCS_COM_DEFEITO = {
    "dfd": "## 1. OBJETO\n\nContrato placeholder meses.\n",
    "etp": "## 1. OBJETO\n\nEstudo técnico.\n",
    "tr": "## 1. OBJETO\n\nTermo de referência.\n",
    "edital": "## 1. OBJETO\n\nEdital.\n",
}
DOCS_CORRIGIDOS = {**DOCS_COM_DEFEITO,
                   "dfd": "## 1. OBJETO\n\nContrato de 12 meses.\n"}


def _app_na_tela_final() -> AppTest:
    import os

    os.environ["GOVDOCS_MODO_ABERTO"] = "1"
    at = AppTest.from_file(APP, default_timeout=60)
    at.secrets["SUPABASE_URL"] = ""
    at.secrets["SUPABASE_KEY"] = ""
    at.session_state["etapa"] = 5
    at.session_state["dados"] = {"orgao": "Prefeitura", "objeto": "canetas"}
    at.session_state["documentos"] = dict(DOCS_COM_DEFEITO)
    at.session_state["aprovados"] = {"dfd", "etp", "tr", "edital"}
    return at


def _resultado_aprovado():
    return {
        "status": "APPROVED", "documentos": dict(DOCS_CORRIGIDOS),
        "versao": 2, "ciclos": 1,
        "relatorios": [{"summary": "1 finding corrigível", "findings": []},
                       {"summary": "aprovado", "findings": []}],
        "planos": [{"operations": [{"op": "replace"}]}],
        "diffs": [{"documentos": {"dfd": {
            "alterados": ["dfd/clausula/1/1"], "adicionados": [],
            "removidos": [], "total_antes": 2}}}],
        "eventos": [], "campos_requeridos": [],
    }


def test_tela_aprovada_corrige_o_bundle_e_libera_downloads(monkeypatch):
    monkeypatch.setattr(
        db, "flag_ativa",
        lambda n: n in (revisao.FLAG_TELA, "correcao_automatica"))
    monkeypatch.setattr(ciclo, "executar_com_persistencia",
                        lambda *a, **k: _resultado_aprovado())
    at = _app_na_tela_final()
    at.run()
    assert not at.exception
    assert at.session_state["documentos"] == DOCS_CORRIGIDOS
    sucessos = " ".join(s.value for s in at.success)
    assert "aprovados para emissão" in sucessos
    # download liberado (a tela antiga bloquearia pelo 'placeholder')
    rotulos = " ".join(b.label or "" for b in at.get("download_button"))
    assert "Baixar todos em PDF" in rotulos


def test_tela_aguardando_dado_pede_somente_o_campo(monkeypatch):
    resultado = {
        "status": "WAITING_REQUIRED_DATA",
        "documentos": dict(DOCS_COM_DEFEITO), "versao": 1, "ciclos": 0,
        "relatorios": [{"summary": "dado ausente", "findings": []}],
        "planos": [], "diffs": [], "eventos": [],
        "campos_requeridos": [{"documento": "dfd",
                               "campo": "prazo de vigência",
                               "findingId": "F001"}],
    }
    monkeypatch.setattr(
        db, "flag_ativa",
        lambda n: n in (revisao.FLAG_TELA, "correcao_automatica"))
    monkeypatch.setattr(ciclo, "executar_com_persistencia",
                        lambda *a, **k: resultado)
    at = _app_na_tela_final()
    at.run()
    assert not at.exception
    rotulos = [i.label or "" for i in at.text_input]
    assert any("prazo de vigência" in r for r in rotulos)
    # emissão continua bloqueada
    assert not [b for b in at.get("download_button")]


def test_flag_off_mantem_a_tela_antiga_de_bloqueio(monkeypatch):
    monkeypatch.setattr(db, "flag_ativa", lambda n: False)
    at = _app_na_tela_final()
    at.run()
    assert not at.exception
    erros = " ".join(e.value for e in at.error)
    assert "Emissão bloqueada" in erros  # atribuição manual preservada
    assert not [b for b in at.get("download_button")]
