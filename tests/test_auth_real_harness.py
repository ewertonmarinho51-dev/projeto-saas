"""Offline admission/bootstrap tests, not proof of real Auth issuance or RLS."""
import hashlib
import io
from pathlib import Path
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


@pytest.mark.parametrize("dsn", ["postgresql://u:p@example.com/db", "postgresql://u:p@localhost/db",
    "postgresql://u:p@127.0.0.1/db?hostaddr=198.51.100.10", "postgresql://u:p@127.0.0.1/db?service=prod",
    "postgresql://u:p@127.0.0.1/db?options=-csearch_path=external",
    "postgresql://u:p@127.0.0.1/db?options=-csearch_path%3Dexternal", "postgresql://u:p@/db?host=/tmp/pg"])
def test_auth_stack_refuses_every_ambiguous_or_remote_database_before_mutation(dsn):
    with pytest.raises((auth_real.AuthRealFailure, ensaio_local.EnsaioLocal)):
        auth_real._local_connection(dsn)


def test_explicit_loopback_database_is_admitted_and_url_escapes_password():
    config = auth_real._local_connection("postgresql://test:test@127.0.0.1:5432/postgres")
    value = auth_real._database_url(config, database="owned", user="own", password="p@ss:/?#")
    assert value == "postgresql://own:p%40ss%3A%2F%3F%23@127.0.0.1:5432/owned?sslmode=disable"


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


def tar_content(name="auth", content=b"\x7fELF\x02\x01synthetic-unit-test-not-executable", symlink=False):
    output = io.BytesIO()
    with tarfile.open(fileobj=output, mode="w:xz") as archive:
        item = tarfile.TarInfo(name)
        if symlink:
            item.type, item.linkname = tarfile.SYMTYPE, "/outside"
            archive.addfile(item)
        else:
            item.size = len(content)
            archive.addfile(item, io.BytesIO(content))
    return output.getvalue()


def synthetic_archive(monkeypatch, tmp_path, **kwargs):
    data = tar_content(**kwargs)
    archive = tmp_path / "synthetic.tar.xz"
    archive.write_bytes(data)
    # Admission algorithm only: these substitutions never enter production/CI.
    monkeypatch.setattr(auth_real, "AUTH_ARCHIVE_BYTES", len(data))
    monkeypatch.setattr(auth_real, "AUTH_ARCHIVE_SHA256", hashlib.sha256(data).hexdigest())
    return archive


def test_archive_hash_is_required_before_any_extraction(tmp_path):
    archive = tmp_path / "untrusted.tar.xz"
    archive.write_bytes(b"untrusted")
    destination = tmp_path / "destination"
    with pytest.raises(auth_real.AuthRealFailure):
        auth_real.stage_auth(archive, destination)
    assert not destination.exists()


@pytest.mark.parametrize("kwargs", [{"name": "../auth"}, {"name": "/auth"}, {"name": "auth", "symlink": True},
                                    {"content": b"not-elf"}, {"name": "unrelated"}])
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


def test_outward_failure_never_prints_exception_body_or_secret(monkeypatch, capsys):
    def fail(**kwargs):
        raise RuntimeError("synthetic-private-password-and-jwt")
    monkeypatch.setattr(auth_real, "executar", fail)
    monkeypatch.setattr("sys.argv", ["auth", "--dsn", "not-printed", "--auth-archive", "/auth", "--postgrest", "/rest",
        "--node", "/node", "--bundle", "/bundle", "--manifest-sha256", "a" * 64, "--work-dir", "/work"])
    assert auth_real.main() == 1
    output = capsys.readouterr().out
    assert "RuntimeError" in output and "private" not in output and "not-printed" not in output


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
