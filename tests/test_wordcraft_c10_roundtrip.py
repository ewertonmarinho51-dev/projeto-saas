import importlib.util
import json
from pathlib import Path
import sys

import pytest


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, ROOT / path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


corpus = load("wordcraft_corpus", "scripts/wordcraft_corpus.py")
roundtrip = load("wordcraft_full_roundtrip", "scripts/wordcraft_full_roundtrip.py")


def c10_bytes(tmp_path):
    manifest = corpus.generate_full(tmp_path / "corpus")
    case = next(item for item in manifest["cases"] if item["id"] == "C10")
    return (tmp_path / "corpus" / case["variants"][0]["docx"]).read_bytes()


def test_c10_fixture_exercises_every_declared_roundtrip_feature(tmp_path):
    snapshot = roundtrip._declared_feature_snapshot(c10_bytes(tmp_path))
    assert snapshot == {
        "nested_table": True,
        "horizontal_merge": True,
        "header": True,
        "footer": True,
        "page_field": True,
        "page_break": True,
    }


def test_c10_controlled_edit_targets_exactly_one_editor_text_node():
    checkpoint = json.dumps({
        "schema": "synthetic",
        "document": {"children": [{"text": "before C10-EXTERNAL after"}]},
        "media": [],
    }).encode()
    checkpoint = checkpoint.replace(b'"children"', b'"body"')
    plan = roundtrip._c10_patch_plan(checkpoint)
    operation = plan["operations"][0]
    assert operation["path"] == [0]
    assert operation["old_text"] == "C10-EXTERNAL"
    assert operation["new_text"] == "C10-EXTERNAL-EDITED"
    assert operation["end_byte"] - operation["start_byte"] == len(b"C10-EXTERNAL")

    duplicated = checkpoint.replace(b"after", b"after C10-EXTERNAL")
    with pytest.raises(ValueError, match="target count differs: 2"):
        roundtrip._c10_patch_plan(duplicated)


def test_checkpoint_item_counter_uses_document_values_and_detects_duplicates():
    checkpoint = json.dumps({
        "schema": "synthetic",
        "document": {
            "GC-C08-0001": "field name is not editor text",
            "body": [
                {"text": "GC-C08-0001"},
                {"children": [{"text": "GC-C08-0002 and GC-C08-0002"}]},
            ],
        },
    }).encode()
    assert roundtrip._checkpoint_code_counts(
        checkpoint, ["GC-C08-0001", "GC-C08-0002", "GC-C08-0003"]) == {
            "GC-C08-0001": 1,
            "GC-C08-0002": 2,
            "GC-C08-0003": 0,
        }


def test_pdf_item_rows_require_every_value_inside_its_own_code_window():
    oracle = {
        "codes": ["ITEM-1", "ITEM-2"],
        "source_items": [
            {"descricao": "Descrição longa um", "unidade": "UN", "quantidade": "2",
             "valor_unitario": "10,00"},
            {"descricao": "Descrição longa dois", "unidade": "CX", "quantidade": "3",
             "valor_unitario": "20,00"},
        ],
        "expected_money": ["R$ 20,00", "R$ 60,00"],
        "global_total_display": "R$ 80,00",
    }
    text = ("ITEM-1 Descrição longa\num UN 2 R$ 10,00 R$ 20,00 "
            "ITEM-2 Descrição longa dois CX 3 R$ 20,00 R$ 60,00 TOTAL R$ 80,00")
    assert roundtrip._pdf_item_row_coverage(text, oracle) == {
        "applicable": True, "checked": 2, "missing": [], "global_total_present": True}

    # A value present in the next row cannot conceal a truncated first row.
    broken = text.replace("ITEM-1 Descrição longa\num UN 2 R$ 10,00 R$ 20,00 ", "ITEM-1 ")
    result = roundtrip._pdf_item_row_coverage(broken, oracle)
    assert result["missing"] == ["ITEM-1"]

