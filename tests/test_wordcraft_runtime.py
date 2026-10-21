import hashlib
import json
from pathlib import Path
import sys

import pytest

from src import wordcraft_runtime as runtime


@pytest.fixture
def release(tmp_path, monkeypatch):
    static = tmp_path / "static" / "wordcraft"
    static.mkdir(parents=True)
    files = []
    for name, data in (("engine.js", b"export default {}"),
                       ("engine.wasm", b"\0asm\x01\0\0\0")):
        (static / name).write_bytes(data)
        files.append({"path": name, "bytes": len(data),
                      "sha256": hashlib.sha256(data).hexdigest()})
    pin = json.loads((Path(__file__).parents[1] /
                      "docs/wordcraft/upstream.lock.json").read_text())["commit"]
    manifest = {"status": runtime.STATUS_OPERACIONAL, "upstream_commit": pin,
                "govconnect_commit": "b" * 40, "files": files}
    raw = json.dumps(manifest).encode()
    (static / "qa-manifest.json").write_bytes(raw)
    notice_files = []
    for index in range(13):
        name = f"notice-{index}.txt"
        data = f"notice {index}\n".encode()
        target = static / "notices" / name
        target.parent.mkdir(exist_ok=True)
        target.write_bytes(data)
        notice_files.append({"path": name,
            "sha256_canonical_lf": hashlib.sha256(data).hexdigest()})
    (static / "notices/manifest.json").write_text(json.dumps({
        "status": "UPSTREAM_AND_FONT_NOTICES_VERIFIED",
        "upstream_commit": pin, "files": notice_files}))
    env = {"GOVDOCS_WORDCRAFT_NODE": sys.executable,
           "GOVDOCS_WORDCRAFT_BUNDLE": str(static),
           "GOVDOCS_WORDCRAFT_MANIFEST_SHA256": hashlib.sha256(raw).hexdigest(),
           "GOVDOCS_WORDCRAFT_ORIGIN": "https://gov.example.invalid"}
    for key, value in env.items():
        monkeypatch.setenv(key, value)
    monkeypatch.setattr(runtime, "STATIC_ROOT", static.parent)
    return static, manifest, env


def test_flag_unica_reusa_config_app_e_default_ausente_e_off(monkeypatch):
    vistos = []
    monkeypatch.setattr(runtime.contexto, "modulo_em_rollout_aqui",
                        lambda name: vistos.append(name) or False)
    assert runtime.ativo() is False
    assert runtime.FLAG == "wordcraft_editor"
    assert vistos == ["wordcraft_editor"]


def test_runtime_admite_somente_tenant_resolvido_pela_sessao(monkeypatch):
    monkeypatch.setattr(runtime.contexto, "modulo_em_rollout_aqui",
                        lambda name: name == runtime.FLAG)
    assert runtime.ativo() is True


def test_release_operacional_valida_hashes_pins_e_urls(release):
    static, manifest, _ = release
    loaded = runtime.carregar()
    assert loaded.bundle == static.resolve()
    assert loaded.node == Path(sys.executable).resolve()
    assert loaded.module_url == "/app/static/wordcraft/engine.js"
    assert loaded.wasm_url == "/app/static/wordcraft/engine.wasm"
    assert loaded.producer_commit == manifest["govconnect_commit"]


@pytest.mark.parametrize("change", ["qa", "asset", "manifest", "origin",
                                     "relative", "extra_entry", "upstream",
                                     "extra_public", "notice"])
def test_runtime_divergente_ou_qa_e_recusado(release, monkeypatch, change):
    static, manifest, env = release
    if change == "qa":
        manifest["status"] = "INTERNAL_LOCAL_QA_ONLY_NOT_DEPLOY_APPROVED"
    elif change == "asset":
        (static / "engine.wasm").write_bytes(b"changed")
    elif change == "origin":
        monkeypatch.setenv("GOVDOCS_WORDCRAFT_ORIGIN", "https://user:pass@example.invalid")
    elif change == "relative":
        monkeypatch.setenv("GOVDOCS_WORDCRAFT_BUNDLE", "static/wordcraft")
    elif change == "extra_entry":
        data = b"other"
        (static / "other.js").write_bytes(data)
        manifest["files"].append({"path": "other.js", "bytes": len(data),
                                  "sha256": hashlib.sha256(data).hexdigest()})
    elif change == "upstream":
        manifest["upstream_commit"] = "c" * 40
    elif change == "extra_public":
        (static / "checkpoint.json").write_text("private")
    elif change == "notice":
        (static / "notices/notice-0.txt").write_text("changed")
    else:
        monkeypatch.setenv("GOVDOCS_WORDCRAFT_MANIFEST_SHA256", "0" * 64)
    if change in {"qa", "extra_entry", "upstream"}:
        raw = json.dumps(manifest).encode()
        (static / "qa-manifest.json").write_bytes(raw)
        monkeypatch.setenv("GOVDOCS_WORDCRAFT_MANIFEST_SHA256",
                           hashlib.sha256(raw).hexdigest())
    with pytest.raises(runtime.ErroRuntime):
        runtime.carregar()


def test_migration_so_registra_flag_desligada():
    sql = (Path(__file__).parents[1] / "supabase/migrations/20261016180000_flag_wordcraft_editor.sql").read_text()
    assert "flag_wordcraft_editor" in sql
    assert "'false'" in sql
    assert "update" not in sql.lower()
