"""Testes da seleção de motor de IA: OpenAI (principal) → Gemini (fallback)."""

import pytest

from src import llm

DADOS = {"orgao": "Órgão X", "objeto": "Objeto Y", "justificativa": "Z"}


@pytest.fixture(autouse=True)
def sem_rag(monkeypatch):
    """Isola a seleção de motor: RAG não consulta banco nestes testes."""
    from src import rag

    monkeypatch.setattr(rag, "montar_bloco_referencias", lambda dados, doc_key: "")


def _configurar(monkeypatch, openai_key: str, gemini_key: str):
    monkeypatch.setattr(llm, "obter_openai_key", lambda: openai_key)
    monkeypatch.setattr(llm, "obter_api_key", lambda: gemini_key)


def test_motor_ativo(monkeypatch):
    _configurar(monkeypatch, "sk-x", "g-y")
    assert llm.motor_ativo() == "openai"
    _configurar(monkeypatch, "", "g-y")
    assert llm.motor_ativo() == "gemini"
    _configurar(monkeypatch, "", "")
    assert llm.motor_ativo() == ""


def test_openai_e_o_motor_principal(monkeypatch):
    _configurar(monkeypatch, "sk-x", "g-y")
    monkeypatch.setattr(llm, "_chamar_openai", lambda s, u, k: "DOC OPENAI")
    monkeypatch.setattr(
        llm, "_chamar_gemini",
        lambda s, u, k: pytest.fail("Gemini não deveria ser chamado"),
    )
    assert llm.gerar_documento("dfd", DADOS, None) == "DOC OPENAI"


def test_fallback_para_gemini_quando_openai_falha(monkeypatch):
    _configurar(monkeypatch, "sk-x", "g-y")

    def openai_quebrada(s, u, k):
        raise llm.ErroGeracaoIA("cota excedida")

    monkeypatch.setattr(llm, "_chamar_openai", openai_quebrada)
    monkeypatch.setattr(llm, "_chamar_gemini", lambda s, u, k: "DOC GEMINI")
    assert llm.gerar_documento("etp", DADOS, "dfd aprovado") == "DOC GEMINI"


def test_erro_propagado_sem_fallback_disponivel(monkeypatch):
    _configurar(monkeypatch, "sk-x", "")

    def openai_quebrada(s, u, k):
        raise llm.ErroGeracaoIA("timeout")

    monkeypatch.setattr(llm, "_chamar_openai", openai_quebrada)
    with pytest.raises(llm.ErroGeracaoIA, match="timeout"):
        llm.gerar_documento("tr", DADOS, "etp aprovado")


def test_sem_nenhuma_chave(monkeypatch):
    _configurar(monkeypatch, "", "")
    with pytest.raises(llm.ErroGeracaoIA, match="Nenhuma chave"):
        llm.gerar_documento("dfd", DADOS, None)
