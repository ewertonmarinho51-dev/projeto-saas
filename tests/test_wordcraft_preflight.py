"""O preflight nunca deve transformar ausência de prova em build aprovado."""
import importlib.util
from pathlib import Path

import pytest

SPEC = importlib.util.spec_from_file_location(
    "wordcraft_preflight", Path(__file__).resolve().parents[1] / "scripts/wordcraft_preflight.py")
preflight = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(preflight)


def test_ambiente_vazio_nao_certifica_build(tmp_path, monkeypatch):
    monkeypatch.setattr(preflight.shutil, "which", lambda _: None)
    r = preflight.inspect(tmp_path)
    assert r["status"] == "BLOCKED" and r["gate1"] == "NOT_RUN"
    assert "tool:cargo" in r["blockers"]
    assert "source:Cargo.lock" in r["blockers"]
    assert not r["production_changed"]


@pytest.mark.parametrize("head,expected", [
    ("wrong-sha", "source:commit_mismatch"),
    ("533615620ef91ae57fa7aa4cd77fd98b2179e693", None),
])
def test_source_precisa_corresponder_ao_pin(tmp_path, monkeypatch, head, expected):
    for rel in preflight.REQUIRED:
        path = tmp_path / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("synthetic", encoding="utf-8")
    (tmp_path / ".git").mkdir()
    monkeypatch.setattr(preflight.shutil, "which", lambda name: name)

    def fake(args, cwd=None):
        if args[:2] == ["git", "rev-parse"]:
            return 0, head
        if args[:2] == ["git", "status"]:
            return 0, ""
        if args[:2] == ["rustup", "target"]:
            return 0, "wasm32-unknown-unknown"
        return 0, "rustc 1.90.0" if args[0] == "rustc" else "test version"

    monkeypatch.setattr(preflight, "run", fake)
    r = preflight.inspect(tmp_path)
    if expected:
        assert expected in r["blockers"] and r["status"] == "BLOCKED"
    else:
        assert r["status"] == "PREREQUISITES_FOUND_NOT_BUILT"
    assert r["gate1"] == "NOT_RUN"


def test_rust_antigo_bloqueado(tmp_path, monkeypatch):
    monkeypatch.setattr(preflight.shutil, "which", lambda name: name)
    monkeypatch.setattr(preflight, "run", lambda *a, **k: (0, "rustc 1.70.0"))
    r = preflight.inspect(tmp_path)
    assert "tool:rust_version_below_minimum" in r["blockers"]
