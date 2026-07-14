"""
Testes do aprendizado institucional (Fase 7 do pacote V5): captura
anonimizada por bloco (KQ-009), edição isolada não vira regra (KQ-010),
publicação exige flag e ato humano (KQ-018), rollback (KQ-019) e flags
desligadas sem efeito (KQ-012).
"""

import pytest

from src import aprendizado, db, governanca, state

ANTES = """## 1. OBJETO

Aquisição de material escolar.

## 2. VIGÊNCIA

Contrato de 12 meses.
"""

DEPOIS = ANTES.replace(
    "Contrato de 12 meses.",
    "Contrato de 12 meses, prorrogável na forma do art. 107. "
    "Contato: fulano@pref.gov.br, CPF 123.456.789-01.")


# ---------------------------------------------------------------------------
# captura (KQ-009 / KQ-010 / KQ-012)
# ---------------------------------------------------------------------------
def test_flag_desligada_nao_captura(monkeypatch):
    monkeypatch.setattr(aprendizado.db, "flag_ativa", lambda n: False)

    def explode(*_a, **_k):
        raise AssertionError("flag OFF não pode persistir")

    monkeypatch.setattr(aprendizado.db, "salvar_feedback", explode)
    assert aprendizado.capturar_edicao("tr", ANTES, DEPOIS, "p1") is None


def test_captura_anonimizada_e_por_bloco(monkeypatch):
    monkeypatch.setattr(
        aprendizado.db, "flag_ativa",
        lambda n: n == governanca.FLAG_APRENDIZADO_CAPTURA)
    monkeypatch.setattr(aprendizado.db, "disponivel", lambda: False)
    feedback = aprendizado.capturar_edicao("tr", ANTES, DEPOIS, "p1")
    assert feedback["status"] == "CAPTURED"
    assert len(feedback["evidencias"]) == 1  # SÓ o bloco alterado
    evidencia = feedback["evidencias"][0]
    assert evidencia["path"] == "tr/clausula/2/1"
    assert "[EMAIL]" in evidencia["depois"]
    assert "[CPF]" in evidencia["depois"]
    assert "fulano@" not in evidencia["depois"]
    assert "Aquisição de material" not in str(feedback["evidencias"])


def test_edicao_sem_mudanca_nao_gera_sinal(monkeypatch):
    monkeypatch.setattr(aprendizado.db, "flag_ativa", lambda n: True)
    assert aprendizado.capturar_edicao("tr", ANTES, ANTES, "p1") is None


def test_aprovacao_dispara_a_captura(monkeypatch):
    import streamlit as st

    capturas = []
    monkeypatch.setattr(aprendizado, "capturar_edicao",
                        lambda *a: capturas.append(a))
    monkeypatch.setattr(state.st, "rerun", lambda: None)
    st.session_state["documentos"] = {"tr": ANTES}
    st.session_state["aprovados"] = set()
    st.session_state["etapa"] = 3
    st.session_state["processo_id"] = "p1"
    st.session_state["dados"] = {}
    state.aprovar_e_avancar("tr", DEPOIS)
    assert capturas == [("tr", ANTES, DEPOIS, "p1")]
    assert st.session_state["documentos"]["tr"] == DEPOIS


# ---------------------------------------------------------------------------
# curadoria: publicação exige flag e humano (KQ-018), rollback (KQ-019)
# ---------------------------------------------------------------------------
def _feedback(status):
    return {"id": "fb1", "status": status, "conteudo": {}, "evidencias": []}


def test_fluxo_completo_ate_publicacao_com_flag(monkeypatch):
    monkeypatch.setattr(aprendizado.db, "flag_ativa", lambda n: True)
    atualizacoes = []
    monkeypatch.setattr(aprendizado.db, "disponivel", lambda: True)
    monkeypatch.setattr(
        aprendizado.db, "atualizar_feedback",
        lambda fid, **c: atualizacoes.append((fid, c)))

    feedback = _feedback("CAPTURED")
    for destino in ("NORMALIZED", "UNDER_REVIEW", "APPROVED_FOR_SHADOW",
                    "SHADOW_VALIDATED"):
        feedback = aprendizado.transicionar(feedback, destino, "curador-1")
    feedback = aprendizado.transicionar(
        feedback, "PUBLISHED", "curador-1", versao_publicada="prompt-tr@4")
    assert feedback["status"] == "PUBLISHED"
    assert atualizacoes[-1][1]["versao_publicada"] == "prompt-tr@4"

    # rollback: publicada → deprecada (nada é apagado)
    feedback = aprendizado.transicionar(feedback, "DEPRECATED", "curador-1")
    assert feedback["status"] == "DEPRECATED"


def test_publicar_sem_flag_e_recusado(monkeypatch):
    monkeypatch.setattr(
        aprendizado.db, "flag_ativa",
        lambda n: n == governanca.FLAG_APRENDIZADO_CAPTURA)
    with pytest.raises(aprendizado.ErroAprendizado, match="desabilitada"):
        aprendizado.transicionar(_feedback("SHADOW_VALIDATED"),
                                 "PUBLISHED", versao_publicada="x@1")
    assert "PUBLISHED" not in aprendizado.proximos_estados(
        _feedback("SHADOW_VALIDATED"))


def test_publicar_sem_rotulo_de_versao_e_recusado(monkeypatch):
    monkeypatch.setattr(aprendizado.db, "flag_ativa", lambda n: True)
    with pytest.raises(aprendizado.ErroAprendizado, match="rótulo"):
        aprendizado.transicionar(_feedback("SHADOW_VALIDATED"), "PUBLISHED")


def test_transicao_invalida_e_erro_explicito(monkeypatch):
    monkeypatch.setattr(aprendizado.db, "flag_ativa", lambda n: True)
    with pytest.raises(aprendizado.ErroAprendizado, match="inválida"):
        aprendizado.transicionar(_feedback("CAPTURED"), "PUBLISHED")


def test_feedback_imutavel_apos_captura(monkeypatch):
    monkeypatch.setattr(db, "disponivel", lambda: True)
    with pytest.raises(db.ErroBanco, match="não atualizáveis"):
        db.atualizar_feedback("fb1", conteudo={"x": 1})
