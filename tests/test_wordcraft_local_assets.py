import hashlib
import importlib.util
import json
from pathlib import Path
import zipfile

import pytest

SPEC = importlib.util.spec_from_file_location(
    "wordcraft_local_assets", Path(__file__).resolve().parents[1] / "scripts/wordcraft_local_assets.py")
assets = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(assets)
PIN = "533615620ef91ae57fa7aa4cd77fd98b2179e693"
PRODUCER = "a" * 40


def fixture(tmp_path, monkeypatch, *, path="editor.js", bad_hash=False, bad_pin=False, bad_wasm=False):
    lab = tmp_path / "lab"
    lab.mkdir()
    (lab / ".wordcraft-local-qa").write_text(assets.MARKER)
    monkeypatch.setattr(assets, "WORK_ROOT", tmp_path)
    files = {path: b"export default async function() {}", "editor.wasm": b"not wasm" if bad_wasm else b"\0asm\x01\0\0\0",
             "snippets/helper.js": b"export const helper = 1;"}
    inventory = [{"path": name, "bytes": len(data), "sha256": hashlib.sha256(data).hexdigest()}
                 for name, data in files.items()]
    if bad_hash:
        inventory[0]["sha256"] = "0" * 64
    notices = {f"wordcraft/notice-{i}.txt": f"Synthetic license fixture {i}\n".encode() for i in range(13)}
    notice_manifest = {"status": "UPSTREAM_AND_FONT_NOTICES_VERIFIED", "upstream_commit": PIN,
        "files": [{"path": name, "sha256_canonical_lf": hashlib.sha256(data).hexdigest()} for name, data in notices.items()]}
    manifest = {"status": "INTERNAL_LOCAL_QA_ONLY_NOT_DEPLOY_APPROVED", "upstream_commit": "b" * 40 if bad_pin else PIN,
                "govconnect_commit": PRODUCER, "files": inventory}
    archive = tmp_path / "bundle.zip"
    with zipfile.ZipFile(archive, "w") as bundle:
        for name, data in files.items(): bundle.writestr(name, data)
        for name, data in notices.items(): bundle.writestr("notices/" + name, data)
        bundle.writestr("qa-manifest.json", json.dumps(manifest))
        bundle.writestr("notices/manifest.json", json.dumps(notice_manifest))
        # Extra private-looking inputs must never be staged in the public namespace.
        bundle.writestr("checkpoint.json", "synthetic document bytes")
        bundle.writestr("cargo-metadata.json", "{}")
    return archive, lab, dict(artifact_sha256=hashlib.sha256(archive.read_bytes()).hexdigest(), producer_commit=PRODUCER)


def test_instalacao_idempotente_so_copia_assets_e_avisos(tmp_path, monkeypatch):
    archive, lab, kwargs = fixture(tmp_path, monkeypatch)
    result = assets.install(archive, lab, **kwargs)
    assert result["module_url"] == "/app/static/wordcraft/editor.js"
    assert result["wasm_url"] == "/app/static/wordcraft/editor.wasm"
    assert assets.install(archive, lab, **kwargs) == result
    target = lab / "static/wordcraft"
    assert (target / "notices/manifest.json").is_file()
    assert not (target / "checkpoint.json").exists()
    assert not (target / "cargo-metadata.json").exists()


@pytest.mark.parametrize("case", ["zip_digest", "asset_digest", "producer", "pin", "traversal", "marker", "foreign_lab", "public_document", "wasm_header"])
def test_bundle_ou_destino_divergente_nao_cria_arquivos(tmp_path, monkeypatch, case):
    path = "../escape.js" if case == "traversal" else "document.json" if case == "public_document" else "editor.js"
    archive, lab, kwargs = fixture(tmp_path, monkeypatch, path=path,
        bad_hash=case == "asset_digest", bad_pin=case == "pin", bad_wasm=case == "wasm_header")
    if case == "zip_digest": kwargs["artifact_sha256"] = "0" * 64
    if case == "producer": kwargs["producer_commit"] = "b" * 40
    if case == "marker": (lab / ".wordcraft-local-qa").write_text("wrong lab")
    if case == "foreign_lab": monkeypatch.setattr(assets, "WORK_ROOT", tmp_path / "another")
    with pytest.raises(ValueError):
        assets.install(archive, lab, **kwargs)
    assert not (lab / "static").exists()


def test_namespace_alheio_e_preservado(tmp_path, monkeypatch):
    archive, lab, kwargs = fixture(tmp_path, monkeypatch)
    target = lab / "static/wordcraft"
    target.mkdir(parents=True)
    (target / "unrelated.txt").write_text("must remain")
    with pytest.raises(ValueError, match="unrelated"):
        assets.install(archive, lab, **kwargs)
    assert (target / "unrelated.txt").read_text() == "must remain"
    assert not (target / "editor.js").exists()


def test_asset_existente_divergente_nao_e_sobrescrito(tmp_path, monkeypatch):
    archive, lab, kwargs = fixture(tmp_path, monkeypatch)
    assets.install(archive, lab, **kwargs)
    target = lab / "static/wordcraft/editor.js"
    target.write_bytes(b"unrelated later edit")
    with pytest.raises(ValueError, match="Existing QA asset differs"):
        assets.install(archive, lab, **kwargs)
    assert target.read_bytes() == b"unrelated later edit"
