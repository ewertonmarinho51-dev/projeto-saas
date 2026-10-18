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

