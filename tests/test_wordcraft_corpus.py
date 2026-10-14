import importlib.util
from pathlib import Path

import pytest

SPEC = importlib.util.spec_from_file_location(
    "wordcraft_corpus", Path(__file__).resolve().parents[1] / "scripts/wordcraft_corpus.py")
corpus = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(corpus)


def test_210_itens_totais_e_fontes_sinteticas():
    table, oracle = corpus.tabela_sintetica()
    assert oracle["items"] == len(set(oracle["codes"])) == 210
    assert all(table.count(code) == 1 for code in oracle["codes"])
    assert table.count("https://example.invalid/precos/") == 210
    assert len(oracle["line_totals_decimal"]) == 210


def test_corpus_docx_preserva_tabela_links_identidade_assinaturas(tmp_path):
    manifest = corpus.generate(tmp_path)
    assert manifest["synthetic_only"]
    cases = manifest["cases"]
    assert cases[0]["hyperlinks"] == 1
    assert cases[1]["table_rows"] == [212]  # header + 210 items + global total
    assert cases[1]["hyperlinks"] == 210
    assert cases[2]["headers"] == cases[2]["footers"] == 1
    inspected = corpus.inspect_docx((tmp_path / "03-timbrado-assinaturas.docx").read_bytes())
    assert "Pessoa Sintética A" in inspected["text"]
    assert "Pessoa Sintética B" in inspected["text"]


def test_pdf_nao_aceita_fallback_como_referencia(tmp_path, monkeypatch):
    monkeypatch.setattr(corpus, "motor_pdf", lambda: "fpdf2")
    with pytest.raises(ValueError, match="LibreOffice"):
        corpus.generate(tmp_path / "corpus", pdf=True)
    assert not (tmp_path / "corpus").exists()
