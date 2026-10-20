from decimal import Decimal

from scripts import wordcraft_ai_scope_benchmark as benchmark


def test_selection_scope_reuses_govbot_prompt_and_reduces_tokens(monkeypatch):
    monkeypatch.setattr(benchmark.wordcraft_corpus, "text_blocks", lambda _data: {
        "body": ["Trecho selecionado para clareza.", "Documento completo " * 200],
        "headers": ["Cabeçalho"], "footers": ["Rodapé"], "links": []})
    monkeypatch.setattr(benchmark.medir_custo, "tokens", lambda value: len(value.encode("utf-8")))
    result = benchmark.measure(b"synthetic-docx")
    assert result["actual_provider_calls"] == 0
    assert result["hypothetical_calls"] == {"selection_edit": 1, "full_regeneration": 1}
    assert result["input_tokens"]["selection_edit"] < result["input_tokens"]["full_regeneration"]
    assert result["input_tokens"]["avoided"] > 0
    assert result["estimated_input_cost_avoided_usd"] is None
    assert result["cost_status"] == "NOT_CALCULATED_NO_MODEL_PRICE"
    assert result["content_persisted"] is False


def test_explicit_input_price_calculates_cost_without_provider_call(monkeypatch):
    monkeypatch.setattr(benchmark.wordcraft_corpus, "text_blocks", lambda _data: {
        "body": ["curto", "longo " * 100], "headers": [], "footers": [], "links": []})
    monkeypatch.setattr(benchmark.medir_custo, "tokens", lambda value: len(value))
    result = benchmark.measure(b"synthetic", input_usd_per_million=Decimal("2.50"))
    expected = Decimal(result["input_tokens"]["avoided"]) * Decimal("2.50") / Decimal(1_000_000)
    assert Decimal(result["estimated_input_cost_avoided_usd"]) == expected
    assert result["cost_status"] == "CALCULATED_FROM_EXPLICIT_INPUT_PRICE"
