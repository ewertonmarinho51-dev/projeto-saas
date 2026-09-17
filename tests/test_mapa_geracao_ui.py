from pathlib import Path
import pytest
from streamlit.testing.v1 import AppTest
from src import db, auth
from src.ui import steps

APP = str(Path(__file__).resolve().parents[1] / "app.py")


@pytest.fixture(autouse=True)
def registro_componentes_por_runtime():
    from src.ui.loading import _componente
    _componente.cache_clear()
    yield
    _componente.cache_clear()


def test_gera_mapa_automaticamente_uma_vez_sem_aprovar(monkeypatch):
    monkeypatch.setattr(db,"flag_ativa",lambda k:k in {"mapa_riscos","loading_overlay"})
    monkeypatch.setattr(db,"disponivel",lambda:False)
    monkeypatch.setattr(db,"em_manutencao",lambda:False)
    monkeypatch.setattr(auth,"modo_aberto",lambda:True)
    monkeypatch.setattr(auth,"precisa_configurar",lambda:False)
    at = AppTest.from_file(APP, default_timeout=30)
    inicial = {"dados":{"orgao":"Teste", "objeto":"Papel", "_fluxo_mapa_riscos":True},
        "documentos":{"dfd":"DFD aprovado", "etp":"ETP aprovado"},
        "aprovados":{"dfd","etp"},"etapa":3,"modo_demo":True}
    for chave, valor in inicial.items():
        at.session_state[chave] = valor
    at.run()
    assert not at.exception
    assert "mapa_riscos" in at.session_state.documentos
    assert "mapa_riscos" not in at.session_state.aprovados
    texto = at.session_state.documentos["mapa_riscos"]
    at.run()
    assert not at.exception
    assert at.session_state.documentos["mapa_riscos"] == texto
    assert at.session_state.etapa == 3


def test_falha_na_arp_preserva_edital_aprovacao_e_rascunho(monkeypatch):
    monkeypatch.setattr(db,"flag_ativa",lambda k:k == "loading_overlay")
    monkeypatch.setattr(db,"disponivel",lambda:False)
    monkeypatch.setattr(db,"em_manutencao",lambda:False)
    monkeypatch.setattr(auth,"modo_aberto",lambda:True)
    monkeypatch.setattr(auth,"precisa_configurar",lambda:False)
    chamadas = []
    def gerar(doc, dados, contexto, **kwargs):
        chamadas.append(doc)
        if doc == "arp":
            raise RuntimeError("Falha sintética")
        return "Nova versão que não deve substituir isoladamente"
    monkeypatch.setattr(steps,"gerar_documento",gerar)
    at = AppTest.from_file(APP,default_timeout=30)
    docs = {k: f"{k} anterior" for k in ["dfd","etp","tr","edital","arp"]}
    inicial = {"dados":{"objeto":"Papel", "modelo_execucao":"Registro de Preços"},
        "documentos":docs.copy(), "aprovados":set(docs),"etapa":4,
        "edicoes_pendentes":{"edital":"Edição humana não aprovada"},
        "_geracao_pedida":{"documento":"edital","id":"retry-1"}}
    for chave,valor in inicial.items():
        at.session_state[chave]=valor
    at.run()
    assert not at.exception
    assert chamadas == ["edital","arp"]
    assert at.session_state.documentos == docs
    assert at.session_state.aprovados == set(docs)
    assert at.session_state.edicoes_pendentes == inicial["edicoes_pendentes"]
    assert at.session_state["_geracao_erro"] == "edital"
    assert any(botao.label == "Tentar novamente" for botao in at.button)
    assert any(campo.value == "Edição humana não aprovada" for campo in at.text_area)
    assert "Falha sintética" not in " ".join(e.value for e in at.error)
    at.run()
    assert chamadas == ["edital","arp"]  # não repete sem pedido humano
