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


def test_fixtures_versionadas_sao_sinteticas_e_byte_identicas_ao_manifesto():
    inputs = Path(__file__).resolve().parent / "fixtures/wordcraft"
    manifest = corpus.verify_inputs(inputs)
    assert manifest["source_run"] == 38620142140
    assert manifest["oracle"]["items"] == 210
    table = corpus.text_blocks((inputs / "02-tabela-210-itens.docx").read_bytes())
    assert len(table["links"]) == 210
    assert all(code in "\n".join(table["body"]) for code in manifest["oracle"]["codes"])


def test_comparador_recusa_texto_perdido_no_retorno(tmp_path):
    inputs = Path(__file__).resolve().parent / "fixtures/wordcraft"
    manifest = corpus.verify_inputs(inputs)
    for item in manifest["files"]:
        target = tmp_path / Path(item["path"]).stem
        target.mkdir()
        (target / "roundtrip.docx").write_bytes((inputs / item["path"]).read_bytes())
        (target / "model.txt").write_text("\n".join(manifest["oracle"]["codes"]), encoding="utf-8")
    assert len(corpus.compare_roundtrip(inputs, tmp_path)["cases"]) == 3
    broken = corpus.gerar_docx("Ensaio", "Texto deliberadamente perdido")
    (tmp_path / "01-texto-listas-links/roundtrip.docx").write_bytes(broken)
    with pytest.raises(ValueError, match="changed semantic"):
        corpus.compare_roundtrip(inputs, tmp_path)
