import pytest
import streamlit as st
from src import state, db, mapa_riscos, achados, validacao
from src.config import sequencia_do_processo, exportaveis_do_processo


@pytest.fixture(autouse=True)
def sessao(monkeypatch):
    st.session_state.clear()
    state.inicializar()
    monkeypatch.setattr(db, "disponivel", lambda: False)
    yield st.session_state
    st.session_state.clear()


def test_historico_preserva_etapa_e_novo_adota_flag(monkeypatch, sessao):
    monkeypatch.setattr(db,"flag_ativa",lambda k: k == "mapa_riscos")
    sessao.dados = {"objeto": "Histórico"}
    state.configurar_fluxo()
    assert state.doc_da_etapa(3) == "tr"
    sessao.clear()
    state.inicializar()
    state.configurar_fluxo()
    assert state.doc_da_etapa(3) == "mapa_riscos"
    assert len(state.sequencia()) == 5


def test_contexto_so_inclui_cadeia_aprovada_e_invalidacao_em_cascata(sessao):
    sessao.dados = {"_fluxo_mapa_riscos": True, "objeto": "Papel"}
    sessao.documentos = {k: k + " aprovado" for k in sequencia_do_processo(sessao.dados)}
    sessao.aprovados = set(sessao.documentos)
    sessao.edicoes_pendentes = {"etp": "RASCUNHO NÃO APROVADO"}
    contexto = state.contexto_para_documento("tr")
    assert all(k + " aprovado" in contexto for k in ["dfd", "etp", "mapa_riscos"])
    assert "RASCUNHO" not in contexto
    state.invalidar_a_partir_de("etp")
    assert set(sessao.documentos) == {"dfd", "etp"}
    assert set(sessao.aprovados) == {"dfd", "etp"}
    assert sessao["_documentos_obsoletos"]["mapa_riscos"] == "etp"


def test_exportacao_e_qualificacao_do_modelo_fornecido():
    dados = {"_fluxo_mapa_riscos": True, "modelo_execucao": "Registro de Preços"}
    docs = {k: "texto" for k in ["arp","edital","tr","mapa_riscos","etp","dfd"]}
    assert exportaveis_do_processo(dados, docs) == ["dfd","etp","mapa_riscos","tr","edital","arp"]
    modelo = mapa_riscos.minuta_demo({"objeto": "Compra de papel"})
    assert "| Id | Ação Preventiva | Responsável |" in modelo
    assert "| Id | Ação de Contingência | Responsável |" in modelo
    assert "Matrícula:" in modelo and "| Impacto:" in modelo
    lista = achados.estruturar(validacao.validar_todos({"mapa_riscos": modelo}), {"mapa_riscos": modelo})
    assert lista and all(a["documentId"] == "mapa_riscos" for a in lista)
