"""
Testes do índice de confiança (Fase 6 do pacote V5): dimensões
determinísticas, crítico bloqueia mesmo com score alto (KQ-006),
mudança de configuração versionada (KQ-013), shadow persiste sem
exibir e gate bloqueia por score baixo.
"""

import streamlit as st

from src import achados, db, fatos, governanca, qualidade

# chaves sem perfil de cláusulas: isolam o score das exigências de
# completude do DFD/ETP/TR (testadas em test_validacao)
BUNDLE_LIMPO = {
    doc: (f"## 1. OBJETO\n\nAquisição de material escolar ({doc}).\n\n"
          "## 2. VALOR\n\nR$ 250,00 conforme planilha.\n")
    for doc in ("doc_a", "doc_b", "doc_c", "doc_d")
}

DADOS = {
    "objeto": "Aquisição de material escolar",
    "modelo_execucao": "Entrega única (fornecimento integral)",
    "valor_estimado": 250.0,
    "itens": [{"descricao": "Caneta", "quantidade": 100,
               "valor_unitario": 2.5}],
}


def _fatos_confirmados():
    lista = fatos.extrair_do_formulario(DADOS, "p1")
    for fato in lista:
        fato["status"] = "confirmado"
    return lista


def _resultado(relatorio=None, lista_fatos=None, decisao=None,
               docs=None, config=None):
    return qualidade.calcular(
        relatorio or achados.gerar_relatorio(docs or BUNDLE_LIMPO, "p1"),
        lista_fatos if lista_fatos is not None else _fatos_confirmados(),
        decisao, docs or BUNDLE_LIMPO, config)


def test_bundle_limpo_com_fatos_confirmados_pontua_alto():
    resultado = _resultado(decisao={"resultado": {
        "bloqueios": [], "conflitos": [], "alertas": []}})
    assert resultado["score"] >= 90
    assert resultado["criticos"] == []
    assert resultado["dimensoes"]["evidenceCoverage"] == 1.0
    assert resultado["dimensoes"]["calculations"] == 1.0
    assert resultado["dimensoes"]["traceability"] == 1.0


def test_score_e_deterministico():
    a = _resultado()
    b = _resultado()
    assert a["score"] == b["score"] and a["dimensoes"] == b["dimensoes"]


# ---------------------------------------------------------------------------
# KQ-006: crítico bloqueia SEMPRE, mesmo com score alto
# ---------------------------------------------------------------------------
def test_ocorrencia_critica_bloqueia_mesmo_com_score_alto():
    relatorio = achados.gerar_relatorio(BUNDLE_LIMPO, "p1")
    relatorio["findings"] = relatorio["findings"] + [{
        "findingId": "S001", "documentId": "tr", "categoria": "semantica",
        "severity": "CRITICAL", "descricao": "vício insanável",
        "evidencia": [], "regraViolada": "", "resultadoEsperado": "",
        "autoCorrectable": False, "allowedPaths": [], "blockedPaths": [],
        "sourceIds": [], "blockingReason": None,
    }]
    resultado = _resultado(relatorio=relatorio)
    avaliacao = qualidade.avaliar_gate(resultado)
    assert resultado["criticos"]
    assert avaliacao["bloqueia"] is True and avaliacao["nivel"] == "critico"


def test_bloqueio_de_regra_do_motor_e_critico():
    decisao = {"resultado": {"bloqueios": [
        {"regra": "regra.x", "motivo": "exige parecer"}],
        "conflitos": [], "alertas": []}}
    resultado = _resultado(decisao=decisao)
    assert resultado["dimensoes"]["policyCompliance"] == 0.0
    assert qualidade.avaliar_gate(resultado)["bloqueia"] is True


def test_score_baixo_bloqueia_por_limiar():
    docs = {"dfd": "## 1. OBJETO\n\n[PREENCHER: tudo]\n"}  # só 1 doc, ruim
    resultado = _resultado(
        relatorio=achados.gerar_relatorio(docs, "p1"),
        lista_fatos=[], docs=docs)
    avaliacao = qualidade.avaliar_gate(resultado)
    assert resultado["score"] < 75 and avaliacao["bloqueia"] is True


# ---------------------------------------------------------------------------
# KQ-013: configuração versionada muda o score de forma rastreável
# ---------------------------------------------------------------------------
def test_mudanca_de_config_altera_score_e_registra_versao():
    config_v2 = {
        "versao": "quality-config@2-teste",
        "pesos": {**qualidade.CONFIG_PADRAO["pesos"],
                  "evidenceCoverage": 0.0, "semanticQuality": 0.3},
        "limiares": qualidade.CONFIG_PADRAO["limiares"],
        "critico_sempre_bloqueia": True,
    }
    v1 = _resultado(lista_fatos=[])
    v2 = _resultado(lista_fatos=[], config=config_v2)
    assert v1["config_versao"] == "quality-config@1"
    assert v2["config_versao"] == "quality-config@2-teste"
    assert v1["score"] != v2["score"]


# ---------------------------------------------------------------------------
# flags: shadow persiste sem exibir; gate devolve para a tela
# ---------------------------------------------------------------------------
def test_shadow_persiste_e_nao_exibe(monkeypatch):
    gravados = []
    monkeypatch.setattr(qualidade.db, "flag_ativa",
                        lambda n: n == governanca.FLAG_SCORE_SHADOW)
    monkeypatch.setattr(qualidade.db, "disponivel", lambda: False)
    monkeypatch.setattr(qualidade.db, "salvar_score",
                        lambda r: gravados.append(r))
    st.session_state.pop("_score_cache", None)
    st.session_state.pop("_decisao_cache", None)
    resultado = qualidade.processar_na_tela(BUNDLE_LIMPO, DADOS, "p1")
    assert resultado is None            # nada na tela
    assert len(gravados) == 1 and gravados[0]["shadow"] is True
    assert gravados[0]["config_versao"] == "quality-config@1"


def test_gate_ligado_devolve_resultado_para_a_tela(monkeypatch):
    monkeypatch.setattr(qualidade.db, "flag_ativa",
                        lambda n: n == governanca.FLAG_SCORE_GATE)
    monkeypatch.setattr(qualidade.db, "disponivel", lambda: False)
    monkeypatch.setattr(qualidade.db, "salvar_score", lambda r: None)
    st.session_state.pop("_score_cache", None)
    st.session_state.pop("_decisao_cache", None)
    resultado = qualidade.processar_na_tela(BUNDLE_LIMPO, DADOS, "p1")
    assert resultado is not None and "score" in resultado


def test_flags_desligadas_nao_calculam(monkeypatch):
    monkeypatch.setattr(qualidade.db, "flag_ativa", lambda n: False)

    def explode(*_a, **_k):
        raise AssertionError("flags OFF não podem calcular score")

    monkeypatch.setattr(qualidade, "calcular", explode)
    assert qualidade.processar_na_tela(BUNDLE_LIMPO, DADOS, "p1") is None
