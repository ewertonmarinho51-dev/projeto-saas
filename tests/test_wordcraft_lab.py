"""Lab guard tests; native execution, SQL and browser proofs remain separate."""
from dataclasses import replace
import hashlib
import importlib.util
import io
import json
from pathlib import Path
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import wordcraft_lab as lab


@pytest.fixture
def configured(tmp_path, monkeypatch):
    root = tmp_path / "repository"
    root.mkdir()
    target = tmp_path / "lab"
    target.mkdir()
    (target / ".wordcraft-local-qa").write_text(lab.MARKER, encoding="utf-8")
    assets = target / "static/wordcraft"
    assets.mkdir(parents=True)
    files = []
    for name, content in (("engine.js", b"synthetic module"), ("engine.wasm", b"synthetic wasm")):
        (assets / name).write_bytes(content)
        files.append({"path": name, "bytes": len(content), "sha256": hashlib.sha256(content).hexdigest()})
    raw = json.dumps({"status": "INTERNAL_LOCAL_QA_ONLY_NOT_DEPLOY_APPROVED", "upstream_commit": "a" * 40, "files": files}).encode()
    (assets / "qa-manifest.json").write_bytes(raw)
    notice_entries = []
    for name in sorted(lab.NOTICE_NAMES):
        path = assets / "notices" / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"synthetic notice\n")
        notice_entries.append({"path": name, "sha256_canonical_lf": hashlib.sha256(path.read_bytes()).hexdigest()})
    (assets / "notices/manifest.json").write_text(json.dumps({"status": "UPSTREAM_AND_FONT_NOTICES_VERIFIED", "upstream_commit": "a" * 40, "files": notice_entries}), encoding="utf-8")
    cluster = tmp_path / "cluster"
    cluster.mkdir()
    (cluster / ".wordcraft-local-qa").write_text(lab.MARKER, encoding="utf-8")
    (cluster / "PG_VERSION").write_text("16\n", encoding="utf-8")
    corpus = tmp_path / "corpus"
    for case in lab.CASES:
        path = corpus / case
        path.mkdir(parents=True)
        (path / "checkpoint.json").write_bytes(case.encode())
    calls = []
    from src import wordcraft_native
    monkeypatch.setattr(wordcraft_native, "validar", lambda content, **configuration: calls.append((content, configuration)))
    monkeypatch.setattr(lab, "ROOT", root)
    monkeypatch.setattr(lab, "WORK_ROOT", tmp_path)
    config = lab.Config(dsn="postgresql://synthetic" + "@127.0.0.1:55439/base?connect_timeout=5", lab=target,
        corpus=corpus, node=Path(sys.executable), postgrest=Path(sys.executable),
        manifest_sha256=hashlib.sha256(raw).hexdigest(), cluster_data=cluster)
    return config, calls


@pytest.mark.parametrize("dsn", [
    "postgresql://synthetic@example.invalid/base", "postgresql://synthetic@localhost/base",
    "postgresql://synthetic" + "@127.0.0.1/base?host=example.invalid",
    "postgresql://synthetic" + "@127.0.0.1/base?service=remote",
    "postgresql://synthetic" + "@127.0.0.1/base?connect_timeout=5&connect_timeout=1",
    "postgresql://synthetic" + "@127.0.0.1/base#unexpected",
    "host=example.invalid dbname=base",
])
def test_remote_or_ambiguous_dsn_rejected_before_engine_or_writes(configured, dsn):
    config, calls = configured
    before = sorted(p.relative_to(config.lab).as_posix() for p in config.lab.rglob("*"))
    with pytest.raises((ValueError, lab.homologacao_local.EnsaioLocal)):
        lab.validate(replace(config, dsn=dsn))
    assert calls == []
    assert sorted(p.relative_to(config.lab).as_posix() for p in config.lab.rglob("*")) == before
    assert "synthetic@" not in repr(config)


def test_validated_assets_and_corpus_are_passed_to_the_same_native_worker(configured):
    config, calls = configured
    result = lab.validate(config)
    assert {k: v for k, v in result.items() if k != "public_files"} == {"module_url": "/app/static/wordcraft/engine.js", "wasm_url": "/app/static/wordcraft/engine.wasm", "host": "127.0.0.1", "port": 55439}
    assert set(result["public_files"]) == {"engine.js", "engine.wasm", "qa-manifest.json", "notices/manifest.json", *("notices/" + name for name in lab.NOTICE_NAMES)}
    assert [content for content, _ in calls] == [case.encode() for case in lab.CASES]
    assert all(conf["bundle"] == config.lab / "static/wordcraft" and conf["manifest_sha256"] == config.manifest_sha256 for _, conf in calls)
    assert not (config.lab / "qa-state.json").exists()


@pytest.mark.parametrize("change", ["marker", "asset", "manifest", "ports", "runtime", "cluster", "extra"])
def test_changed_scope_or_asset_never_reaches_engine(configured, change):
    config, calls = configured
    if change == "marker":
        (config.lab / ".wordcraft-local-qa").write_text("foreign lab")
    elif change == "asset":
        (config.lab / "static/wordcraft/engine.wasm").write_bytes(b"changed")
    elif change == "manifest":
        (config.lab / "static/wordcraft/qa-manifest.json").write_bytes(b"{}")
    elif change == "ports":
        config = replace(config, gateway_port=config.rest_port)
    elif change == "cluster":
        (config.cluster_data / ".wordcraft-local-qa").write_text("foreign cluster")
    elif change == "extra":
        (config.lab / "static/wordcraft/checkpoint.json").write_bytes(b"private synthetic checkpoint")
    else:
        config = replace(config, node=Path("relative"))
    with pytest.raises(ValueError):
        lab.validate(config)
    assert calls == []


def test_occupied_port_never_creates_or_reuses_a_database(configured, monkeypatch):
    config, _ = configured
    monkeypatch.setattr(lab.stack, "_porta_livre", lambda port: False)
    monkeypatch.setattr(lab, "prepare", lambda *args: pytest.fail("no database mutation permitted"))
    with pytest.raises(ValueError, match="port occupied"):
        lab.serve(config)


def test_reused_state_cannot_redirect_the_lab_to_another_database(configured):
    config, _ = configured
    (config.lab / "qa-state.json").write_text(json.dumps({"schema": "gc-wordcraft-lab/v1", "database": "production"}), encoding="utf-8")
    with pytest.raises(ValueError, match="Lab state"):
        lab.prepare(config, {"host": "127.0.0.1", "port": 55439})


@pytest.mark.parametrize("name", ["PGHOSTADDR", "PGSERVICE", "PGOPTIONS", "PGRST_DB_URI"])
def test_inherited_libpq_configuration_is_rejected_before_execution(configured, monkeypatch, name):
    config, calls = configured
    monkeypatch.setenv(name, "192.0.2.15")
    with pytest.raises(ValueError, match="Inherited PostgreSQL"):
        lab.validate(config)
    assert calls == []


def test_effective_libpq_address_and_port_are_pinned(configured):
    import psycopg
    config, _ = configured
    actual = psycopg.conninfo.conninfo_to_dict(lab.pinned_dsn(config.dsn))
    assert actual["host"] == actual["hostaddr"] == "127.0.0.1"
    assert actual["port"] == "55439"


def test_stdin_stop_allows_graceful_cleanup_without_killing_the_parent():
    class Child:
        def poll(self): return None
    assert lab.wait_for_stop(Child(), io.StringIO("stop\n")) == 0


def test_terminal_child_does_not_wait_for_a_stop_command():
    class Child:
        returncode = 7
        def poll(self): return self.returncode
    assert lab.wait_for_stop(Child(), io.StringIO("")) == 7


def test_wrong_cluster_identity_prevents_database_bootstrap(configured, monkeypatch):
    import psycopg
    config, _ = configured
    class Connection:
        def __enter__(self): return self
        def __exit__(self, *args): return False
        def execute(self, query):
            assert query.startswith("select ")
            return self
        def fetchone(self): return (str(config.cluster_data), "*", "127.0.0.1", 55439)
    monkeypatch.setattr(psycopg, "connect", lambda *args, **kwargs: Connection())
    monkeypatch.setattr(lab.stack, "_porta_livre", lambda port: True)
    monkeypatch.setattr(lab, "prepare", lambda *args: pytest.fail("no mutation before cluster identity"))
    with pytest.raises(ValueError, match="disposable loopback cluster"):
        lab.serve(config)


def test_public_route_never_serves_an_unlisted_file_added_after_preflight(configured, monkeypatch):
    from starlette.applications import Starlette
    from starlette.routing import Mount
    from starlette.testclient import TestClient
    import streamlit
    config, _ = configured
    plan = lab.validate(config)
    monkeypatch.setenv("GOVDOCS_WORDCRAFT_LAB", json.dumps({"origin": "http://127.0.0.1:8884", "lab": str(config.lab), **plan}))
    monkeypatch.setenv("SUPABASE_URL", "http://127.0.0.1:55451")
    monkeypatch.setenv("SUPABASE_KEY", "synthetic")
    monkeypatch.setenv("SUPABASE_SERVICE_KEY", "synthetic")
    monkeypatch.setattr(streamlit, "App", lambda *args, **kwargs: None)
    spec = importlib.util.spec_from_file_location("wordcraft_lab_server_test", Path(__file__).resolve().parents[1] / "integrations/wordcraft/lab/server.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    directory = config.lab / "static/wordcraft"
    private = b"private synthetic checkpoint"
    (directory / "checkpoint.json").write_bytes(private)
    app = Starlette(routes=[Mount("/assets", app=module.PublicAssets(directory, plan["public_files"]))])
    with TestClient(app) as client:
        assert client.get("/assets/engine.js").status_code == 200
        response = client.get("/assets/checkpoint.json")
        assert response.status_code == 404 and private not in response.content
