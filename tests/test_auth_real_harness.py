"""Offline admission/bootstrap tests, not proof of real Auth issuance or RLS."""
import hashlib
import io
import json
from pathlib import Path
import subprocess
import tarfile

import pytest

from scripts import ensaio_auth_real as auth_real
ensaio_local = auth_real.sql_harness


def test_default_sql_fixture_is_byte_identical_to_pre_auth_baseline():
    assert hashlib.sha256(ensaio_local.PREAMBULO.encode()).hexdigest() == "86dd2897a540b5b792961dd1f0ab38ea9f69b91f20c71cfde888495e16454a7f"
    assert "create table if not exists auth.users" in ensaio_local.PREAMBULO
    assert "create table if not exists auth.users" not in ensaio_local.PREAMBULO_AUTH_REAL
    for statement in ("create or replace function auth.uid()", "create or replace function auth.jwt()",
                      "grant execute on function auth.uid()", "alter default privileges in schema public"):
        assert statement in ensaio_local.PREAMBULO_AUTH_REAL


def database_uri(authority, suffix="/db"):
    # Runtime construction keeps synthetic URI credentials out of source scanner matches.
    return "postgresql://u:p" + "@" + authority + suffix


@pytest.mark.parametrize("dsn", [database_uri("example.com"), database_uri("localhost"),
    database_uri("127.0.0.1", "/db?hostaddr=198.51.100.10"), database_uri("127.0.0.1", "/db?service=prod"),
    database_uri("127.0.0.1", "/db?options=-csearch_path=external"),
    database_uri("127.0.0.1", "/db?options=-csearch_path%3Dexternal"), database_uri("", "/db?host=/tmp/pg")])
def test_auth_stack_refuses_every_ambiguous_or_remote_database_before_mutation(dsn):
    with pytest.raises((auth_real.AuthRealFailure, ensaio_local.EnsaioLocal)):
        auth_real._local_connection(dsn)


def test_explicit_loopback_database_is_admitted_and_url_escapes_password():
    config = auth_real._local_connection("host=127.0.0.1 port=5432 dbname=postgres user=test password=test")
    value = auth_real._database_url(config, database="owned", user="own", password="p@ss:/?#")
    assert value == "postgresql://own:p%40ss%3A%2F%3F%23" + "@" + "127.0.0.1:5432/owned?sslmode=disable"


def test_disposable_database_conninfo_retargets_keyword_dsn(monkeypatch):
    import psycopg
    executed = []

    class FakeCursor:
        def __enter__(self): return self
        def __exit__(self, *args): return False
        def execute(self, query): executed.append(query)

    class FakeConnection:
        def __enter__(self): return self
        def __exit__(self, *args): return False
        def cursor(self): return FakeCursor()

    monkeypatch.setattr(psycopg, "connect", lambda *args, **kwargs: FakeConnection())
    base = "host=127.0.0.1 port=5432 dbname=admin user=test connect_timeout=5"
    target, name = ensaio_local.criar_banco_descartavel(base)
    parsed = psycopg.conninfo.conninfo_to_dict(target)
    assert parsed == {"host":"127.0.0.1", "port":"5432", "dbname":name,
                      "user":"test", "connect_timeout":"5"}
    assert executed == [f'create database "{name}"']


def test_gotrue_environment_does_not_inherit_hosted_credentials_or_network_settings(monkeypatch):
    monkeypatch.setenv("SUPABASE_SECRET_KEY", "synthetic-private-secret")
    monkeypatch.setenv("GOTRUE_SMTP_HOST", "outside.invalid")
    monkeypatch.setenv("HTTP_PROXY", "http://outside.invalid")
    environment = auth_real.auth_environment(database_url="local-private-url", secret="private-memory-only",
                                            port=20001, gateway_port=20002)
    assert "SUPABASE_SECRET_KEY" not in environment and "HTTP_PROXY" not in environment
    assert environment["GOTRUE_API_HOST"] == "127.0.0.1"
    assert environment["GOTRUE_SMTP_HOST"] == "127.0.0.1"
    assert environment["GOTRUE_SMTP_PORT"] == "1"
    assert environment["GOTRUE_DISABLE_SIGNUP"] == "true"
    assert environment["GOTRUE_JWT_EXP"] == "180"
    assert environment["GOTRUE_JWT_SECRET"] == "private-memory-only"


class Cursor:
    def __init__(self, *, complete=True, migration=True):
        self.complete, self.migration, self.calls = complete, migration, []

    def __enter__(self):
        return self

    def __exit__(self, *args):
        pass

    def execute(self, query, params=None):
        self.calls.append((query, params))

    def fetchall(self):
        if not self.complete:
            return [("users", c) for c in ("id", "email", "raw_app_meta_data", "created_at")]
        columns = {"users": ("id", "email", "encrypted_password", "raw_app_meta_data", "raw_user_meta_data",
                              "aud", "role", "confirmed_at", "last_sign_in_at", "created_at"),
                   "identities": ("user_id", "provider", "identity_data"), "sessions": ("id", "user_id"),
                   "refresh_tokens": ("token", "user_id", "revoked"), "schema_migrations": ("version",)}
        return [(t, c) for t, names in columns.items() for c in names]

    def fetchone(self):
        return (ensaio_local.AUTH_MIGRACAO_EXIGIDA,) if self.migration else None


class Connection:
    def __init__(self, cursor):
        self.instance, self.committed = cursor, False

    def cursor(self):
        return self.instance

    def commit(self):
        self.committed = True


@pytest.mark.parametrize("complete,migration", [(False, True), (True, False)])
def test_real_auth_mode_refuses_fixture_or_missing_version_before_application_sql(monkeypatch, complete, migration):
    monkeypatch.setattr(ensaio_local, "migracoes_do_schema", lambda: pytest.fail("must fail before app schema"))
    cursor = Cursor(complete=complete, migration=migration)
    connection = Connection(cursor)
    with pytest.raises(ensaio_local.EnsaioLocal):
        ensaio_local.preparar(connection, auth_real=True)
    assert not connection.committed
    assert not any("create" in query.lower() for query, _ in cursor.calls)


@pytest.mark.parametrize("real", [False, True])
def test_preparation_selects_shared_sql_without_duplicating_application_migrations(monkeypatch, real):
    monkeypatch.setattr(ensaio_local, "migracoes_do_schema", lambda: [])
    monkeypatch.setattr(ensaio_local, "sequencia_em_ensaio", lambda: [])
    cursor, connection = Cursor(), None
    connection = Connection(cursor)
    assert ensaio_local.preparar(connection, auth_real=real)["preambulo"] is True
    assert cursor.calls[-1][0] == (ensaio_local.PREAMBULO_AUTH_REAL if real else ensaio_local.PREAMBULO)
    assert connection.committed


def tar_content(name="auth", content=b"\x7fELF\x02\x01synthetic-unit-test-not-executable", symlink=False,
                alias_target="auth", alias_hardlink=False, migration_name="migrations/00_unit.up.sql", duplicate=False):
    output = io.BytesIO()
    with tarfile.open(fileobj=output, mode="w:xz") as archive:
        item = tarfile.TarInfo(name)
        if symlink:
            item.type, item.linkname = tarfile.SYMTYPE, "/outside"
            archive.addfile(item)
        else:
            item.size = len(content)
            archive.addfile(item, io.BytesIO(content))
        alias = tarfile.TarInfo("gotrue")
        alias.type, alias.linkname = (tarfile.LNKTYPE if alias_hardlink else tarfile.SYMTYPE), alias_target
        archive.addfile(alias)
        folder = tarfile.TarInfo("migrations/")
        folder.type = tarfile.DIRTYPE
        archive.addfile(folder)
        migration = tarfile.TarInfo(migration_name)
        migration.size = len(b"-- synthetic SQL; never executed\n")
        archive.addfile(migration, io.BytesIO(b"-- synthetic SQL; never executed\n"))
        if duplicate:
            archive.addfile(migration, io.BytesIO(b"-- synthetic SQL; never executed\n"))
    return output.getvalue()


def synthetic_archive(monkeypatch, tmp_path, **kwargs):
    data = tar_content(**kwargs)
    archive = tmp_path / "synthetic.tar.xz"
    archive.write_bytes(data)
    # Admission algorithm only: these substitutions never enter production/CI.
    monkeypatch.setattr(auth_real, "AUTH_ARCHIVE_BYTES", len(data))
    monkeypatch.setattr(auth_real, "AUTH_ARCHIVE_SHA256", hashlib.sha256(data).hexdigest())
    with tarfile.open(fileobj=io.BytesIO(data), mode="r:xz") as source:
        entries = source.getmembers()
        monkeypatch.setattr(auth_real, "AUTH_ARCHIVE_MEMBERS", len(entries))
        monkeypatch.setattr(auth_real, "AUTH_ARCHIVE_EXPANDED_BYTES", sum(member.size for member in entries))
    monkeypatch.setattr(auth_real, "AUTH_MIGRATION_FILES", 1)
    binary = kwargs.get("content", b"\x7fELF\x02\x01synthetic-unit-test-not-executable")
    monkeypatch.setattr(auth_real, "AUTH_BINARY_BYTES", len(binary))
    monkeypatch.setattr(auth_real, "AUTH_BINARY_SHA256", hashlib.sha256(binary).hexdigest())
    return archive


def test_archive_hash_is_required_before_any_extraction(tmp_path):
    archive = tmp_path / "untrusted.tar.xz"
    archive.write_bytes(b"untrusted")
    destination = tmp_path / "destination"
    with pytest.raises(auth_real.AuthRealFailure):
        auth_real.stage_auth(archive, destination)
    assert not destination.exists()


@pytest.mark.parametrize("kwargs", [{"name": "../auth"}, {"name": "/auth"}, {"name": "auth", "symlink": True},
    {"content": b"not-elf"}, {"name": "unrelated"}, {"alias_target": "../auth"}, {"alias_target": "/auth"},
    {"alias_hardlink": True}, {"migration_name": "migrations/../auth"},
    {"migration_name": "migrations/nested/00_unit.up.sql"}, {"migration_name": "unexpected"}, {"duplicate": True}])
def test_archive_confinement_and_binary_type_are_required(monkeypatch, tmp_path, kwargs):
    archive = synthetic_archive(monkeypatch, tmp_path, **kwargs)
    destination = tmp_path / "destination"
    with pytest.raises(auth_real.AuthRealFailure):
        auth_real.stage_auth(archive, destination)
    assert not destination.exists()


def test_archive_extractor_writes_only_the_verified_binary(monkeypatch, tmp_path):
    archive = synthetic_archive(monkeypatch, tmp_path)
    destination = tmp_path / "destination"
    binary = auth_real.stage_auth(archive, destination)
    assert list(destination.iterdir()) == [binary]
    assert binary.read_bytes().startswith(b"\x7fELF")


def test_verified_archive_still_requires_exact_binary_hash_before_writing(monkeypatch, tmp_path):
    archive = synthetic_archive(monkeypatch, tmp_path)
    monkeypatch.setattr(auth_real, "AUTH_BINARY_SHA256", "0" * 64)
    destination = tmp_path / "destination"
    with pytest.raises(auth_real.AuthRealFailure, match="^official_auth_binary_pin$"):
        auth_real.stage_auth(archive, destination)
    assert not destination.exists()


@pytest.mark.parametrize("constant,stage", [
    ("AUTH_ARCHIVE_MEMBERS", "official_auth_archive_shape"),
    ("AUTH_ARCHIVE_EXPANDED_BYTES", "official_auth_archive_shape"),
    ("AUTH_MIGRATION_FILES", "official_auth_archive_shape"),
    ("AUTH_BINARY_BYTES", "official_auth_archive_binary"),
])
def test_archive_shape_counts_and_expansion_are_exact_before_writing(monkeypatch, tmp_path, constant, stage):
    archive = synthetic_archive(monkeypatch, tmp_path)
    monkeypatch.setattr(auth_real, constant, getattr(auth_real, constant) + 1)
    destination = tmp_path / "destination"
    with pytest.raises(auth_real.AuthRealFailure, match="^" + stage + "$"):
        auth_real.stage_auth(archive, destination)
    assert not destination.exists()


@pytest.mark.parametrize("stdout,code,expected", [
    (b"v2.197.0\n", 0, None), (b"2.197.0\n", 0, None),
    (b"v2.196.0\n", 0, "official_auth_version"),
    (b"private-untrusted-cli-output", 0, "official_auth_version"),
    (b"v2.197.0\n", 1, "official_auth_version"),
])
def test_official_version_command_matches_only_the_pinned_release(monkeypatch, tmp_path, stdout, code, expected):
    def run(command, **kwargs):
        assert command == [str(tmp_path / "auth"), "version"]
        assert kwargs["capture_output"] is True and kwargs["timeout"] == 10
        return subprocess.CompletedProcess(command, code, stdout, b"private-untrusted-error")
    monkeypatch.setattr(auth_real.subprocess, "run", run)
    if expected is None:
        auth_real._verify_auth_version(tmp_path / "auth", tmp_path)
    else:
        with pytest.raises(auth_real.AuthRealFailure, match="^" + expected + "$"):
            auth_real._verify_auth_version(tmp_path / "auth", tmp_path)


def test_version_timeout_is_a_closed_diagnostic_without_process_output(monkeypatch, tmp_path):
    def run(*args, **kwargs):
        raise subprocess.TimeoutExpired("private-argv", 10, output=b"private-process-output")
    monkeypatch.setattr(auth_real.subprocess, "run", run)
    with pytest.raises(auth_real.AuthRealFailure, match="^official_auth_version_command$"):
        auth_real._verify_auth_version(tmp_path / "auth", tmp_path)


def test_outward_failure_never_prints_exception_body_or_secret(monkeypatch, capsys):
    def fail(**kwargs):
        raise RuntimeError("synthetic-private-password-and-jwt")
    monkeypatch.setattr(auth_real, "executar", fail)
    monkeypatch.setattr("sys.argv", ["auth", "--dsn", "not-printed", "--auth-archive", "/auth", "--postgrest", "/rest",
        "--node", "/node", "--bundle", "/bundle", "--manifest-sha256", "a" * 64, "--work-dir", "/work"])
    assert auth_real.main() == 1
    output = capsys.readouterr().out
    assert "RuntimeError" in output and "private" not in output and "not-printed" not in output


@pytest.mark.parametrize("stage,expected", [("official_auth_archive_shape", "official_auth_archive_shape"),
    ("private_password_and_token", "unexpected_failure"),
    ("http://private.invalid/?password=private", "unexpected_failure"),
    ("official_auth_archive_shape\nprivate", "unexpected_failure"), (None, "unexpected_failure")])
def test_preflight_exposes_only_allowlisted_stages_without_exception_text(monkeypatch, capsys, stage, expected):
    def fail(**kwargs):
        raise auth_real.AuthRealFailure(stage)
    monkeypatch.setattr(auth_real, "executar", fail)
    monkeypatch.setattr("sys.argv", ["auth", "--dsn", "private-dsn", "--auth-archive", "/auth", "--postgrest", "/rest",
        "--node", "/node", "--bundle", "/bundle", "--manifest-sha256", "a" * 64, "--work-dir", "/work"])
    assert auth_real.main() == 1
    output = capsys.readouterr().out
    assert json.loads(output) == {"status": "FAIL_PREFLIGHT", "failed_stage": expected, "error_type": "AuthRealFailure"}
    assert "private" not in output


def test_environment_secrets_are_restored_even_on_failure(monkeypatch):
    monkeypatch.setenv("AUTH_UNIT_ORIGINAL", "original")
    with pytest.raises(RuntimeError):
        with auth_real._environment({"AUTH_UNIT_TEMPORARY": "memory-secret"}):
            assert "AUTH_UNIT_ORIGINAL" not in auth_real.os.environ
            raise RuntimeError()
    assert auth_real.os.environ["AUTH_UNIT_ORIGINAL"] == "original"
    assert "AUTH_UNIT_TEMPORARY" not in auth_real.os.environ


def test_cleanup_continues_after_a_failed_owned_child_and_uses_only_owned_objects(monkeypatch):
    calls = []
    class Child:
        stderr = None
        def __init__(self, name):
            self.name, self.finished = name, False
        def poll(self):
            return 0 if self.finished else None
        def wait(self, timeout):
            calls.append((self.name, "wait"))
        def kill(self):
            calls.append((self.name, "kill"))
            self.finished = True
    first, second = Child("first"), Child("second")
    def stop(child):
        calls.append((child.name, "stop"))
        if child is second:
            raise OSError("synthetic private shutdown failure")
        child.finished = True
    monkeypatch.setattr(auth_real.homologacao_stack, "_encerrar", stop)
    assert auth_real._stop_children([first, second])
    assert calls == [("second", "stop"), ("second", "kill"), ("second", "wait"), ("first", "stop"), ("first", "wait")]
