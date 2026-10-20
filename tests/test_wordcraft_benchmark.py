import hashlib
import json
from pathlib import Path

import pytest

from scripts import wordcraft_benchmark as benchmark
from scripts import wordcraft_corpus as corpus


def _sha(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _roundtrip(tmp_path: Path):
    cases = []
    artifacts = {}
    for number in range(16):
        case = f"C{number + 1:02d}"
        source = f"{case}/doc.docx"
        root = tmp_path / case / "doc"
        root.mkdir(parents=True)
        values = {
            "checkpoint.json": f"checkpoint-{case}".encode(),
            "roundtrip.docx": f"docx-{case}".encode(),
            "roundtrip.pdf": f"pdf-{case}".encode(),
        }
        for name, value in values.items():
            (root / name).write_bytes(value)
        pages = 29 if case == "C02" else 1
        items = 210 if case == "C08" else 0
        cases.append({"case": case, "source": source,
            "checkpoint_sha256": _sha(values["checkpoint.json"]),
            "checkpoint_bytes": len(values["checkpoint.json"]),
            "docx_sha256": _sha(values["roundtrip.docx"]), "docx_bytes": len(values["roundtrip.docx"]),
            "pdf_sha256": _sha(values["roundtrip.pdf"]), "pdf_bytes": len(values["roundtrip.pdf"]),
            "pdf_pages": pages, "pdf_item_code_count": items,
            "steps": {"native": "PASS", "export": "PASS"}})
        artifacts[values["checkpoint.json"]] = values
    receipt = {"schema": "gc-wordcraft-full-roundtrip/v1",
        "status": "NATIVE_EXECUTION_FIDELITY_NOT_APPROVED",
        "engine_manifest_sha256": "a" * 64, "cases": cases}
    (tmp_path / "comparison.json").write_text(json.dumps(receipt), encoding="utf-8")
    return artifacts


def test_hundred_page_fixture_is_deterministic_and_has_explicit_boundaries():
    first = benchmark._synthetic_paged_docx(100)
    second = benchmark._synthetic_paged_docx(100)
    inspection = corpus.inspect_full_docx(first)
    assert first == second
    assert inspection["explicit_page_breaks"] == 99
    assert "GC-SCALE-PAGE-001" in inspection["text"]
    assert "GC-SCALE-PAGE-100" in inspection["text"]


def test_full_roundtrip_benchmark_admits_all_cases_and_measures_scale(tmp_path, monkeypatch):
    artifacts = _roundtrip(tmp_path)
    monkeypatch.setattr(benchmark, "_runtime", lambda *args: {"engine": "synthetic"})
    monkeypatch.setattr(benchmark, "validar", lambda content, **kwargs: None)
    monkeypatch.setattr(benchmark, "exportar", lambda content, *, formato, **kwargs:
                        artifacts[content]["roundtrip." + formato] if content in artifacts else b"%PDF-scale")
    monkeypatch.setattr(benchmark, "_synthetic_paged_docx", lambda pages: f"scale-docx-{pages}".encode())
    monkeypatch.setattr(benchmark, "importar_docx", lambda content, **kwargs: b"scale-checkpoint-" + content.rsplit(b"-", 1)[1])
    monkeypatch.setattr(benchmark, "exportar", lambda content, *, formato, **kwargs:
                        artifacts[content]["roundtrip." + formato] if content in artifacts
                        else b"%PDF-scale-" + content.rsplit(b"-", 1)[1])
    monkeypatch.setattr(benchmark, "_pdf_pages", lambda content: int(content.rsplit(b"-", 1)[1]))
    result = benchmark.benchmark_full_roundtrip(node=Path("node").resolve(),
        bundle=Path("bundle").resolve(), manifest_sha256="a" * 64,
        roundtrip=tmp_path, repetitions=2)
    assert result["schema"] == "gc-wordcraft-native-benchmark/v2"
    assert result["coverage"] == {"case_count": 16, "maximum_pdf_pages": 29,
        "contains_at_least_twenty_pages": True, "contains_210_item_case": True,
        "contains_20_page_scale_profile": True,
        "contains_100_page_scale_profile": True}
    assert all(case["operations"]["validate"]["sample_count"] == 2 for case in result["cases"])
    assert result["method"]["scale_page_counts_measured"] == [20, 100]
    assert [profile["pdf_pages"] for profile in result["scale_profiles"]] == [20, 100]


@pytest.mark.parametrize("change", ["hash", "duplicate", "step"])
def test_full_roundtrip_benchmark_fails_closed_before_measurement(tmp_path, monkeypatch, change):
    _roundtrip(tmp_path)
    receipt_path = tmp_path / "comparison.json"
    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    if change == "hash":
        receipt["cases"][0]["checkpoint_sha256"] = "0" * 64
    elif change == "duplicate":
        receipt["cases"][1]["case"] = receipt["cases"][0]["case"]
        receipt["cases"][1]["source"] = receipt["cases"][0]["source"]
    else:
        receipt["cases"][0]["steps"]["export"] = "FAIL"
    receipt_path.write_text(json.dumps(receipt), encoding="utf-8")
    monkeypatch.setattr(benchmark, "_runtime", lambda *args: {"engine": "synthetic"})
    calls = []
    monkeypatch.setattr(benchmark, "validar", lambda *args, **kwargs: calls.append("validate"))
    with pytest.raises(ValueError):
        benchmark.benchmark_full_roundtrip(node=Path("node").resolve(),
            bundle=Path("bundle").resolve(), manifest_sha256="a" * 64,
            roundtrip=tmp_path, repetitions=1)
    assert calls == []
