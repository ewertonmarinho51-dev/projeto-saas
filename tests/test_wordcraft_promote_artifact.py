import hashlib
import json
from pathlib import Path

import pytest

from scripts.wordcraft_promote_artifact import promover, RELEASE_STATUS


SHA = "1" * 40
APPROVAL = "2" * 40


def _write(path: Path, value):
    path.write_text(json.dumps(value), encoding="utf-8")


def _fixture(tmp_path: Path):
    bundle = tmp_path / "bundle"
    (bundle / "notices").mkdir(parents=True)
    (bundle / "editor.js").write_bytes(b"js")
    (bundle / "editor.wasm").write_bytes(b"\0asm\x01\0\0\0")
    files = []
    for name in ("editor.js", "editor.wasm"):
        data = (bundle / name).read_bytes()
        files.append({"path": name, "bytes": len(data),
                      "sha256": hashlib.sha256(data).hexdigest()})
    _write(bundle / "qa-manifest.json", {
        "status": "INTERNAL_LOCAL_QA_ONLY_NOT_DEPLOY_APPROVED",
        "upstream_commit": "3" * 40,
        "govconnect_commit": SHA,
        "files": files,
    })
    _write(bundle / "notices" / "manifest.json", {
        "status": "UPSTREAM_AND_FONT_NOTICES_VERIFIED",
        "upstream_commit": "3" * 40,
    })
    paths = {name: tmp_path / f"{name}.json" for name in
             ("build_run", "build_artifacts", "fidelity_run", "fidelity_artifacts")}
    _write(paths["build_run"], {"id": 10, "path": ".github/workflows/wordcraft-build.yml",
                                "status": "completed", "conclusion": "success", "head_sha": SHA})
    _write(paths["fidelity_run"], {"id": 20, "path": ".github/workflows/wordcraft-fidelity.yml",
                                   "status": "completed", "conclusion": "success", "head_sha": SHA})
    _write(paths["build_artifacts"], {"artifacts": [{
        "id": 30, "name": "wordcraft-govconnect-local-qa", "expired": False,
        "digest": "sha256:" + "4" * 64, "workflow_run": {"id": 10}}]})
    _write(paths["fidelity_artifacts"], {"artifacts": [{
        "id": 40, "name": "wordcraft-synthetic-fidelity-20-1", "expired": False,
        "digest": "sha256:" + "5" * 64, "workflow_run": {"id": 20}}]})
    return bundle, paths


def test_promove_somente_execucoes_reconciliadas(tmp_path):
    bundle, p = _fixture(tmp_path)
    (bundle / "cargo-metadata.json").write_text("evidência de QA", encoding="utf-8")
    output = tmp_path / "release"
    result = promover(bundle, p["build_run"], p["build_artifacts"],
                      p["fidelity_run"], p["fidelity_artifacts"], APPROVAL, output)
    manifest = json.loads((output / "qa-manifest.json").read_text(encoding="utf-8"))
    assert result["status"] == manifest["status"] == RELEASE_STATUS
    assert manifest["release_evidence"]["build_run_id"] == 10
    assert manifest["release_evidence"]["fidelity_run_id"] == 20
    assert not (output / "cargo-metadata.json").exists()


def test_recusa_fidelidade_de_outro_commit(tmp_path):
    bundle, p = _fixture(tmp_path)
    fidelity = json.loads(p["fidelity_run"].read_text(encoding="utf-8"))
    fidelity["head_sha"] = "9" * 40
    _write(p["fidelity_run"], fidelity)
    with pytest.raises(ValueError, match="mesmo commit"):
        promover(bundle, p["build_run"], p["build_artifacts"],
                 p["fidelity_run"], p["fidelity_artifacts"], APPROVAL,
                 tmp_path / "release")


def test_recusa_bundle_que_nao_e_qa(tmp_path):
    bundle, p = _fixture(tmp_path)
    manifest = json.loads((bundle / "qa-manifest.json").read_text(encoding="utf-8"))
    manifest["status"] = RELEASE_STATUS
    _write(bundle / "qa-manifest.json", manifest)
    with pytest.raises(ValueError, match="não corresponde"):
        promover(bundle, p["build_run"], p["build_artifacts"],
                 p["fidelity_run"], p["fidelity_artifacts"], APPROVAL,
                 tmp_path / "release")
