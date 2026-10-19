"""O preflight nunca deve transformar ausência de prova em build aprovado."""
import importlib.util
from pathlib import Path
import hashlib
import json
import zipfile

import pytest

SPEC = importlib.util.spec_from_file_location(
    "wordcraft_preflight", Path(__file__).resolve().parents[1] / "scripts/wordcraft_preflight.py")
preflight = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(preflight)


def test_lock_descreve_estado_integrado_sem_promover_producao():
    lock = json.loads((preflight.ROOT / "docs/wordcraft/upstream.lock.json").read_text(
        encoding="utf-8"))
    assert lock["build_status"].startswith("INTEGRATED_ADAPTER_VERIFIED_")
    assert lock["bridge_status"] == "CONNECTED_TO_DOCUMENT_SERVICE_IN_LOCAL_QA_AUTH_REAL_PENDING"
    assert lock["canonical_format"] == "GC_WORDCRAFT_SNAPSHOT_V1_SELECTED_HOMOLOGATION_PENDING"
    assert lock["production_rollout"] is False


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


def baseline_fixture(tmp_path, monkeypatch, *, evidence_sha="a" * 40):
    source = tmp_path / "source"
    source.mkdir()
    (source / "Cargo.lock").write_bytes(b"synthetic locked input\n")
    digest = hashlib.sha256((source / "Cargo.lock").read_bytes()).hexdigest()
    archive = tmp_path / "baseline.zip"
    with zipfile.ZipFile(archive, "w") as bundle:
        bundle.writestr("upstream-sha.txt", evidence_sha + "\n")
        bundle.writestr("Cargo.lock.sha256", digest + "  Cargo.lock\n")
    lock = {"commit": "a" * 40, "baseline_run": 123, "baseline_govconnect_commit": "b" * 40,
            "baseline_artifact_sha256": hashlib.sha256(archive.read_bytes()).hexdigest()}
    metadata = {"id": 123, "head_sha": "b" * 40, "status": "completed", "conclusion": "success",
                "repository": {"full_name": "ewertonmarinho51-dev/projeto-saas"}}
    monkeypatch.setattr(preflight, "run", lambda args, cwd=None: (0, "a" * 40) if "rev-parse" in args else (0, ""))
    return archive, metadata, source, lock


def test_reuso_baseline_verifica_prova_sem_aprovar_adaptador(tmp_path, monkeypatch):
    args = baseline_fixture(tmp_path, monkeypatch)
    result = preflight.verify_baseline(*args)
    assert result["status"] == "BASELINE_EVIDENCE_VERIFIED_NOT_ADAPTER_APPROVED"
    assert result["gate1"] == "NOT_RUN"


@pytest.mark.parametrize("case", ["run_failed", "run_sha", "repository", "archive", "lock", "dirty", "head"])
def test_baseline_divergente_nao_e_reutilizado(tmp_path, monkeypatch, case):
    archive, metadata, source, lock = baseline_fixture(tmp_path, monkeypatch)
    if case == "run_failed": metadata["conclusion"] = "failure"
    if case == "run_sha": metadata["head_sha"] = "c" * 40
    if case == "repository": metadata["repository"]["full_name"] = "another/repository"
    if case == "archive": archive.write_bytes(archive.read_bytes() + b"altered")
    if case == "lock": (source / "Cargo.lock").write_bytes(b"changed input")
    if case == "dirty":
        monkeypatch.setattr(preflight, "run", lambda args, cwd=None: (0, "a" * 40) if "rev-parse" in args else (0, " M source"))
    if case == "head": monkeypatch.setattr(preflight, "run", lambda *args, **kwargs: (0, "wrong-sha"))
    with pytest.raises(ValueError):
        preflight.verify_baseline(archive, metadata, source, lock)


def test_baseline_zip_de_outro_upstream_e_rejeitado(tmp_path, monkeypatch):
    args = baseline_fixture(tmp_path, monkeypatch, evidence_sha="c" * 40)
    with pytest.raises(ValueError, match="another upstream"):
        preflight.verify_baseline(*args)
