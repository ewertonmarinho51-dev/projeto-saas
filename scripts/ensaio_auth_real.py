"""Official GoTrue + canonical SQL/HTTP + native document owner, local CI only.

Downloads are performed separately by CI and pinned. This harness only executes
an authenticated official archive in a fresh disposable local DB. No secrets,
HTTP error bodies, DSNs or service logs are emitted into its evidence.
"""
from __future__ import annotations

import argparse
import base64
from contextlib import contextmanager
import hashlib
import hmac
import io
import json
import logging
import os
from pathlib import Path
import re
import secrets
import socket
import subprocess
import sys
import tarfile
import time
from urllib.parse import quote
import urllib.request
import uuid

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
if str(ROOT / "scripts") not in sys.path:
    sys.path.insert(0, str(ROOT / "scripts"))
import ensaio_local as sql_harness
import homologacao_local
import homologacao_stack
from gateway_supabase import SemRedirect, destino_loopback

AUTH_VERSION = "v2.197.0"
AUTH_COMMIT = "4eee58f296d9698a1c2c0ae14d7a0b379c7622d3"
AUTH_ARCHIVE_BYTES = 9_897_464
AUTH_ARCHIVE_SHA256 = "b5c2991d1df760c9b099c1c2395a94bd1c2f83ed58901934921997179dc9f7ea"
AUTH_ARCHIVE_MEMBERS = 78
AUTH_ARCHIVE_EXPANDED_BYTES = 37_408_505
AUTH_BINARY_BYTES = 37_343_392
AUTH_BINARY_SHA256 = "c66b5efc816ccf3e13c24022bdefd5c6a9bea1fd1a1aeb9c586e1279c75a6306"
AUTH_MIGRATION_FILES = 75
JWT_EXPIRY_SECONDS = 180
LOCAL_HOSTS = frozenset({"127.0.0.1", "::1"})
FAILURE_STAGES = frozenset({
    "unexpected_failure", "preflight", "invalid_local_database_configuration",
    "explicit_loopback_database_required", "official_auth_linux_required", "explicit_binaries_required",
    "native_manifest_pin", "fresh_work_directory_required", "official_auth_archive_read",
    "official_auth_archive_pin", "official_auth_archive_shape", "official_auth_archive_binary",
    "official_auth_elf", "official_auth_binary_pin", "official_auth_version_command", "official_auth_version",
    "create_database", "bootstrap_roles", "unique_loopback_ports", "official_gotrue_migrations",
    "canonical_app_migrations", "start_services", "real_gotrue_health", "real_auth_owner_proofs",
    "bounded_auth_response", "auth_response_object", "bounded_gotrue_token", "gotrue_token_algorithm",
    "gotrue_token_signature", "real_gotrue_user_claims", "product_configuration_is_owned_loopback",
    "admin_app_metadata_in_real_token", "gotrue_user_endpoint", "real_gotrue_session_row",
    "product_password_login", "server_client_not_replaced_by_login",
    "native_checkpoint_matches_pinned_synthetic_fixture", "owner_native_commit",
    "rls_owner", "rls_colleague", "rls_other", "no_user_client_fallback",
    "app_metadata_admin_privilege_required", "user_app_metadata_update_not_refused",
    "user_cannot_update_app_metadata", "user_metadata_is_not_authorization",
    "postgrest_uses_controlled_app_metadata", "owner_second_commit", "old_revision_bytes_immutable",
    "old_export_artifact_immutable", "denied_writes_left_exactly_two_revisions",
    "refresh_revocation_is_auth_denial", "revoked_refresh_accepted",
    "banned_auth_account_cannot_password_login", "revoked_profile_cannot_read_with_old_jwt",
    "revocation_did_not_write_partial_revision",
} | {gate + suffix for gate in (
    "non_owner_commit_colleague", "non_owner_commit_other", "anonymous_revision_read", "anonymous_owner_open",
    "service_cannot_mutate_revision", "revoked_profile_cannot_commit_with_old_jwt",
) for suffix in ("_inconclusive", "_unexpectedly_allowed")})
ERROR_TYPES = frozenset({"AuthRealFailure", "EnsaioLocal", "RuntimeError", "ValueError", "TypeError",
    "OSError", "FileNotFoundError", "FileExistsError", "PermissionError", "TimeoutExpired",
    "OperationalError", "ProgrammingError", "HTTPError", "URLError", "JSONDecodeError", "UnicodeDecodeError"})


def _safe_stage(stage) -> str:
    return stage if (type(stage) is str and re.fullmatch(r"[a-z][a-z0-9_]{0,79}", stage)
                     and stage in FAILURE_STAGES) else "unexpected_failure"


class AuthRealFailure(RuntimeError):
    """Only a fixed stage name is allowed in outward evidence."""

    def __init__(self, stage):
        self.stage = _safe_stage(stage)
        super().__init__(self.stage)


def _failure_record(error: Exception, *, fallback: str) -> dict:
    return {"failed_stage": _safe_stage(error.stage if isinstance(error, AuthRealFailure) else fallback),
            "error_type": type(error).__name__ if type(error).__name__ in ERROR_TYPES else "UnexpectedError"}


def _sha(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def _check(condition, stage: str) -> None:
    if condition is not True:
        raise AuthRealFailure(stage)


def _local_connection(dsn: str) -> dict:
    import psycopg
    try:
        sql_harness.exigir_dsn_local(dsn)
        config = psycopg.conninfo.conninfo_to_dict(dsn)
    except (sql_harness.EnsaioLocal, psycopg.Error, TypeError, ValueError):
        raise AuthRealFailure("invalid_local_database_configuration") from None
    if (config.get("host") not in LOCAL_HOSTS or not config.get("dbname")
            or not config.get("user") or "hostaddr" in config or "service" in config
            or set(config) - {"host", "dbname", "user", "password", "port", "sslmode", "connect_timeout"}
            or not config.get("port", "5432").isdigit()
            or not 1 <= int(config.get("port", "5432")) <= 65535):
        raise AuthRealFailure("explicit_loopback_database_required")
    return config


def _database_url(config: dict, *, database: str, user: str, password: str) -> str:
    host = "[::1]" if config["host"] == "::1" else config["host"]
    return (f"postgresql://{quote(user, safe='')}:{quote(password, safe='')}@{host}:"
            f"{config.get('port', '5432')}/{quote(database, safe='')}?sslmode=disable")


def stage_auth(archive: Path, destination: Path) -> Path:
    """Pin before extracting one regular ELF; never unpack arbitrary members."""
    try:
        with archive.open("rb") as stream:
            raw = stream.read(AUTH_ARCHIVE_BYTES + 1)
    except OSError:
        raise AuthRealFailure("official_auth_archive_read") from None
    _check(len(raw) == AUTH_ARCHIVE_BYTES and _sha(raw) == AUTH_ARCHIVE_SHA256,
           "official_auth_archive_pin")
    try:
        with tarfile.open(fileobj=io.BytesIO(raw), mode="r:xz") as source:
            entries = source.getmembers()
            names = [member.name.rstrip("/") for member in entries]
            _check(len(entries) == AUTH_ARCHIVE_MEMBERS and len(set(names)) == len(names)
                   and sum(member.size for member in entries) == AUTH_ARCHIVE_EXPANDED_BYTES,
                   "official_auth_archive_shape")
            migrations = 0
            for member, name in zip(entries, names):
                if name == "auth":
                    allowed = member.name == "auth" and member.isfile()
                elif name == "gotrue":
                    # Official backwards-compatible alias. Validate only; never extract/follow it.
                    allowed = member.name == "gotrue" and member.issym() and member.linkname == "auth" and member.size == 0
                elif name == "migrations":
                    allowed = member.isdir() and member.size == 0
                else:
                    allowed = (member.isfile() and member.size <= 1024 * 1024
                        and re.fullmatch(r"migrations/(?:[0-9]{2}|[0-9]{14})_[a-z0-9_]+(?:\.postgres)?\.up\.sql", member.name))
                    migrations += bool(allowed)
                _check(bool(allowed), "official_auth_archive_shape")
            _check(set(names) >= {"auth", "gotrue", "migrations"} and migrations == AUTH_MIGRATION_FILES,
                   "official_auth_archive_shape")
            binaries = [member for member in entries if member.name == "auth" and member.isfile()]
            _check(len(binaries) == 1 and binaries[0].size == AUTH_BINARY_BYTES, "official_auth_archive_binary")
            with source.extractfile(binaries[0]) as stream:
                content = stream.read(AUTH_BINARY_BYTES + 1)
            _check(content.startswith(b"\x7fELF\x02\x01"), "official_auth_elf")
            _check(len(content) == AUTH_BINARY_BYTES and _sha(content) == AUTH_BINARY_SHA256, "official_auth_binary_pin")
    except (tarfile.TarError, OSError, EOFError):
        raise AuthRealFailure("official_auth_archive_shape") from None
    destination.mkdir(mode=0o700)
    target = destination / "auth"
    target.write_bytes(content)
    target.chmod(0o700)
    return target


def _verify_auth_version(binary: Path, work: Path) -> None:
    try:
        version = subprocess.run([str(binary), "version"], cwd=work, env=_child_environment(),
                                 capture_output=True, timeout=10, check=False)
    except (OSError, subprocess.TimeoutExpired):
        raise AuthRealFailure("official_auth_version_command") from None
    _check(version.returncode == 0 and version.stdout in {
        (AUTH_VERSION + "\n").encode("ascii"), (AUTH_VERSION[1:] + "\n").encode("ascii")}, "official_auth_version")


def _child_environment() -> dict:
    return {key: os.environ[key] for key in ("PATH", "HOME", "LANG", "LC_ALL", "TMP", "TEMP",
                                            "SystemRoot", "WINDIR") if key in os.environ}


def auth_environment(*, database_url: str, secret: str, port: int, gateway_port: int) -> dict:
    base = _child_environment()
    external = f"http://127.0.0.1:{gateway_port}/auth/v1"
    base.update({"GOTRUE_DB_DRIVER": "postgres", "DATABASE_URL": database_url, "DB_NAMESPACE": "auth",
        "GOTRUE_API_HOST": "127.0.0.1", "PORT": str(port), "API_EXTERNAL_URL": external,
        "GOTRUE_SITE_URL": f"http://127.0.0.1:{gateway_port}",
        "GOTRUE_JWT_SECRET": secret, "GOTRUE_JWT_EXP": str(JWT_EXPIRY_SECONDS),
        "GOTRUE_JWT_AUD": "authenticated", "GOTRUE_JWT_DEFAULT_GROUP_NAME": "authenticated",
        "GOTRUE_JWT_ADMIN_ROLES": "service_role", "GOTRUE_JWT_ISSUER": external,
        "GOTRUE_DISABLE_SIGNUP": "true", "GOTRUE_EXTERNAL_EMAIL_ENABLED": "true",
        "GOTRUE_EXTERNAL_PHONE_ENABLED": "false", "GOTRUE_MAILER_AUTOCONFIRM": "true",
        "GOTRUE_SMTP_HOST": "127.0.0.1", "GOTRUE_SMTP_PORT": "1",
        "GOTRUE_PASSWORD_MIN_LENGTH": "12", "GOTRUE_DB_MAX_POOL_SIZE": "4",
        "GOTRUE_SECURITY_REFRESH_TOKEN_ROTATION_ENABLED": "true",
        "GOTRUE_LOG_LEVEL": "error", "LOG_LEVEL": "error"})
    return base


def _available_port() -> int:
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        return listener.getsockname()[1]


def _stop_children(processes) -> bool:
    """A single failed child must not prevent cleanup of the other owned PIDs."""
    complete = True
    for process in reversed(processes):
        try:
            homologacao_stack._encerrar(process)
            process.wait(timeout=10)
        except Exception:
            try:
                if process.poll() is None:
                    process.kill()
                    process.wait(timeout=5)
            except Exception:
                complete = False
        finally:
            if process.stderr is not None:
                try:
                    process.stderr.close()
                except Exception:
                    complete = False
        complete = complete and process.poll() is not None
    return complete


def _http_json(url: str, *, method="GET", token=None, body=None) -> dict:
    # All callers construct a fixed local origin; never follow an OAuth redirect.
    from urllib.parse import urlsplit
    origin = urlsplit(url)
    destino_loopback(f"{origin.scheme}://{origin.netloc}")
    headers = {"Content-Type": "application/json"}
    if token is not None:
        headers["Authorization"] = "Bearer " + token
    request = urllib.request.Request(url, method=method, headers=headers,
        data=json.dumps(body).encode("utf-8") if body is not None else None)
    with urllib.request.build_opener(SemRedirect).open(request, timeout=10) as response:
        raw = response.read(1024 * 1024 + 1)
        _check(len(raw) <= 1024 * 1024, "bounded_auth_response")
        result = json.loads(raw)
        _check(isinstance(result, dict), "auth_response_object")
        return result


def _claims(token: str, secret: str, *, user_id: str, issuer: str) -> dict:
    """Verify a token RETURNED by GoTrue; this never creates a user token."""
    _check(isinstance(token, str) and len(token) <= 32_768, "bounded_gotrue_token")
    header, payload, signature = token.split(".")
    decode = lambda part: base64.urlsafe_b64decode(part + "=" * (-len(part) % 4))
    _check(json.loads(decode(header)).get("alg") == "HS256", "gotrue_token_algorithm")
    expected = hmac.new(secret.encode(), (header + "." + payload).encode(), hashlib.sha256).digest()
    _check(hmac.compare_digest(expected, decode(signature)), "gotrue_token_signature")
    value = json.loads(decode(payload))
    _check(value.get("sub") == user_id and value.get("role") == "authenticated"
        and value.get("aud") == "authenticated" and value.get("iss") == issuer
        and type(value.get("exp")) is int and type(value.get("iat")) is int
        and 0 < value["exp"] - value["iat"] <= JWT_EXPIRY_SECONDS
        and value["exp"] > time.time() and isinstance(value.get("session_id"), str), "real_gotrue_user_claims")
    return value


@contextmanager
def _environment(values):
    previous = dict(os.environ)
    os.environ.clear()
    os.environ.update(values)
    try:
        yield
    finally:
        os.environ.clear()
        os.environ.update(previous)


@contextmanager
def _user(token):
    from src import db
    import streamlit as st
    previous = st.session_state.get(db.CHAVE_DA_SESSAO)
    if token is None:
        st.session_state.pop(db.CHAVE_DA_SESSAO, None)
    else:
        st.session_state[db.CHAVE_DA_SESSAO] = token
    try:
        yield
    finally:
        if previous is None:
            st.session_state.pop(db.CHAVE_DA_SESSAO, None)
        else:
            st.session_state[db.CHAVE_DA_SESSAO] = previous


def _denied(operation, stage):
    from src.documentos_editor import AcessoNegado
    try:
        operation()
    except AcessoNegado:
        return
    except Exception as error:
        if getattr(error, "code", None) in {"42501", "PGRST301", "PGRST302"}:
            return
        raise AuthRealFailure(stage + "_inconclusive") from None
    raise AuthRealFailure(stage + "_unexpectedly_allowed")


def _proof(*, database_dsn, config, secret, gateway_port, server_key, public_key, evidence):
    """Exercise existing product clients and owner; no alternative SQL/app engine."""
    import psycopg
    from src import auth, db, wordcraft_native
    from src.documentos_editor import DocumentoService
    from src.wordcraft_protocol import Checkpoint
    from scripts import wordcraft_corpus as corpus
    from supabase import __version__ as sdk_version

    _check(db._config() == (f"http://127.0.0.1:{gateway_port}", server_key)
           and db._segredo(db.NOME_CHAVE_PUBLICA) == public_key,
           "product_configuration_is_owned_loopback")
    service = db._cliente()
    accounts = {}
    for label in ("owner", "colleague", "other"):
        tenant_key = "a" if label != "other" else "b"
        if tenant_key not in accounts:
            tenant = service.table("tenants").insert({"slug": "auth-qa-" + uuid.uuid4().hex, "nome": "Auth QA", "uf": "PA"}).execute().data[0]["id"]
            secretary = service.table("secretarias").insert({"tenant_id": tenant, "nome": "Auth QA", "sigla": "QA"}).execute().data[0]["id"]
            accounts[tenant_key] = {"tenant_id": tenant, "secretaria_id": secretary, "papel": "usuario"}
        metadata = accounts[tenant_key]
        email, password = uuid.uuid4().hex + "@example.invalid", secrets.token_urlsafe(32)
        created = service.auth.admin.create_user({"email": email, "password": password,
            "email_confirm": True, "app_metadata": metadata})
        uid = str(created.user.id)
        service.table("usuarios").insert({"nome": "Auth QA", "login": email,
            "senha_hash": "not-a-login-credential", "papel": "usuario", "tenant_id": metadata["tenant_id"],
            "secretaria_id": metadata["secretaria_id"], "auth_user_id": uid}).execute()
        login = auth._cliente_de_login()
        signed = login.auth.sign_in_with_password({"email": email, "password": password})
        claims = _claims(signed.session.access_token, secret, user_id=uid,
            issuer=f"http://127.0.0.1:{gateway_port}/auth/v1")
        _check(all(claims["app_metadata"].get(k) == v for k, v in metadata.items()), "admin_app_metadata_in_real_token")
        _check(str(login.auth.get_user(signed.session.access_token).user.id) == uid, "gotrue_user_endpoint")
        with psycopg.connect(database_dsn) as connection:
            row = connection.execute("select count(*) from auth.sessions where id=%s and user_id=%s",
                                     (claims["session_id"], uid)).fetchone()
            _check(row == (1,), "real_gotrue_session_row")
        accounts[label] = {"id": uid, "email": email, "password": password, "login": login,
            "token": signed.session.access_token, "refresh": signed.session.refresh_token, "metadata": metadata}
    owner = accounts["owner"]
    # Also run the product's exact password-login adapter, separate from server.
    product_login = auth.autenticar_no_supabase(owner["email"], owner["password"])
    _check(product_login is not None and product_login[1] == owner["id"], "product_password_login")
    owner["token"] = product_login[0]
    _check(service.table("config_app").select("chave").limit(0).execute().data == [], "server_client_not_replaced_by_login")
    process = service.table("processos").insert({"tenant_id": accounts["a"]["tenant_id"],
        "secretaria_id": accounts["a"]["secretaria_id"], "auth_user_id": owner["id"],
        "orgao": "Auth QA", "objeto": "Synthetic Auth QA", "dados": {}}).execute().data[0]["id"]
    cases = corpus.verify_inputs(ROOT / "tests/fixtures/wordcraft")
    fixture_path = ROOT / "tests/fixtures/wordcraft" / cases["files"][0]["path"]
    fixture = fixture_path.read_bytes()
    checkpoint = wordcraft_native.importar_docx(fixture, **config)
    _check(corpus.text_blocks(wordcraft_native.exportar(checkpoint, formato="docx", **config)) == corpus.text_blocks(fixture),
           "native_checkpoint_matches_pinned_synthetic_fixture")
    documents = DocumentoService(**config)
    with _user(owner["token"]):
        current = documents.criar(processo_id=process, tipo="memo", payload=checkpoint, operation_id=str(uuid.uuid4()))
        _check(current.revision == 1 and current.payload == checkpoint, "owner_native_commit")
        artifact = documents.exportar(current.id, expected_revision=1, content_hash=current.content_hash, formato="docx")
    artifact_before = _sha(artifact.payload)
    for label, expected in (("owner", 1), ("colleague", 1), ("other", 0)):
        with _user(accounts[label]["token"]):
            client = db.cliente_do_usuario()
            visible = client.table("documentos_editor_revisoes").select("document_id").eq("document_id", current.id).execute().data
            _check(len(visible) == expected, "rls_" + label)
            if label != "owner":
                _denied(lambda: documents.checkpoint(current.id, Checkpoint(str(uuid.uuid4()), 1, current.content_hash, checkpoint)),
                        "non_owner_commit_" + label)
    anonymous = auth._cliente_de_login()
    _denied(lambda: anonymous.table("documentos_editor_revisoes").select("document_id").eq("document_id", current.id).execute(),
            "anonymous_revision_read")
    with _user(None):
        _check(db.cliente_do_usuario() is None, "no_user_client_fallback")
        _denied(lambda: documents.abrir(current.id), "anonymous_owner_open")
    # A user can edit user_metadata, and cannot thereby acquire server claims.
    attack = dict(accounts["b"], papel="admin", papel_governanca="admin_municipal")
    owner["login"].auth.update_user({"data": attack})
    try:
        _http_json(f"http://127.0.0.1:{gateway_port}/auth/v1/user", method="PUT", token=owner["token"],
                   body={"app_metadata": attack})
    except urllib.error.HTTPError as error:
        _check(error.code == 403, "app_metadata_admin_privilege_required")
    else:
        raise AuthRealFailure("user_app_metadata_update_not_refused")
    updated = _http_json(f"http://127.0.0.1:{gateway_port}/auth/v1/user", token=owner["token"])
    _check(all(updated["app_metadata"].get(k) == v for k, v in accounts["a"].items()), "user_cannot_update_app_metadata")
    refreshed = owner["login"].auth.refresh_session(owner["refresh"])
    claims = _claims(refreshed.session.access_token, secret, user_id=owner["id"],
                     issuer=f"http://127.0.0.1:{gateway_port}/auth/v1")
    _check(all(claims["app_metadata"].get(k) == v for k, v in accounts["a"].items())
           and claims["user_metadata"].get("tenant_id") == accounts["b"]["tenant_id"], "user_metadata_is_not_authorization")
    owner["token"], owner["refresh"] = refreshed.session.access_token, refreshed.session.refresh_token
    with _user(owner["token"]):
        context = db.cliente_do_usuario().rpc("documento_editor_contexto", {}).execute().data
        _check(context["app_metadata"]["tenant_id"] == accounts["a"]["tenant_id"], "postgrest_uses_controlled_app_metadata")
        receipt = documents.checkpoint(current.id, Checkpoint(str(uuid.uuid4()), 1, current.content_hash, checkpoint))
        _check(receipt.revision == 2, "owner_second_commit")
        _check(documents.abrir_revisao(current.id, 1).payload == checkpoint, "old_revision_bytes_immutable")
        _check(_sha(artifact.payload) == artifact_before and artifact.revision == 1, "old_export_artifact_immutable")
    _denied(lambda: service.table("documentos_editor_revisoes").update({"payload": "\\x00"})
            .eq("document_id", current.id).eq("revision", 1).execute(), "service_cannot_mutate_revision")
    rows = service.table("documentos_editor_revisoes").select("revision,content_hash").eq("document_id", current.id).order("revision").execute().data
    _check(len(rows) == 2 and all(row["content_hash"] == current.content_hash for row in rows), "denied_writes_left_exactly_two_revisions")
    # GoTrue revokes refresh sessions. An already issued JWT can still satisfy
    # PostgREST signature/expiry checks; this distinction is an observed result.
    owner["login"].auth.sign_out({"scope": "global"})
    try:
        auth._cliente_de_login().auth.refresh_session(owner["refresh"])
    except Exception as error:
        _check(getattr(error, "status", None) in {400, 401, 403, 422}, "refresh_revocation_is_auth_denial")
    else:
        raise AuthRealFailure("revoked_refresh_accepted")
    with _user(owner["token"]):
        still_visible = db.cliente_do_usuario().table("documentos_editor").select("id").eq("id", current.id).execute().data
    service.auth.admin.update_user_by_id(owner["id"], {"ban_duration": "1h"})
    _check(auth.autenticar_no_supabase(owner["email"], owner["password"]) is None, "banned_auth_account_cannot_password_login")
    service.table("usuarios").update({"ativo": False}).eq("auth_user_id", owner["id"]).execute()
    with _user(owner["token"]):
        _check(db.cliente_do_usuario().table("documentos_editor").select("id").eq("id", current.id).execute().data == [],
               "revoked_profile_cannot_read_with_old_jwt")
        _denied(lambda: documents.checkpoint(current.id, Checkpoint(str(uuid.uuid4()), 2, current.content_hash, checkpoint)),
                "revoked_profile_cannot_commit_with_old_jwt")
    final_rows = service.table("documentos_editor_revisoes").select("revision,content_hash").eq("document_id", current.id).order("revision").execute().data
    _check(final_rows == rows, "revocation_did_not_write_partial_revision")
    evidence.update({"sdk_supabase_version": sdk_version, "users_authenticated_by_password": 3,
        "native_checkpoint_sha256": _sha(checkpoint), "fixture_docx_sha256": _sha(fixture),
        "native_revisions_saved": 2, "artifact_sha256": artifact_before, "artifact_bytes": len(artifact.payload),
        "checks": {key: True for key in ("real_gotrue_password_login", "real_auth_schema_and_session_rows", "controlled_app_metadata",
            "user_metadata_cannot_promote", "tenant_a_b_rls", "same_tenant_colleague_reads_but_cannot_commit", "anonymous_denied",
            "canonical_owner_native_save", "immutable_revision_and_artifact", "refresh_token_revocation", "auth_account_ban",
            "profile_revocation_blocks_old_jwt_read_and_save", "denied_operations_have_no_partial_writes")},
        "logout_access_token_observation": {"accepted_by_postgrest_before_profile_revocation": bool(still_visible),
            "immediate_access_token_revocation_claimed": False}, "jwt_expiry_seconds": JWT_EXPIRY_SECONDS})


def executar(*, dsn: str, archive: Path, postgrest: Path, node: Path, bundle: Path,
             manifest_sha256: str, work: Path) -> dict:
    admin_config = _local_connection(dsn)  # Before every file/DB/process mutation.
    _check(sys.platform == "linux", "official_auth_linux_required")
    _check(all(path.is_absolute() and path.is_file() for path in (archive, postgrest, node)), "explicit_binaries_required")
    _check(bundle.is_absolute() and bundle.is_dir() and (bundle / "qa-manifest.json").is_file()
           and _sha((bundle / "qa-manifest.json").read_bytes()) == manifest_sha256,
           "native_manifest_pin")
    _check(not work.exists(), "fresh_work_directory_required")
    work.mkdir(parents=True, mode=0o700)
    binary = stage_auth(archive, work / "auth-bin")
    _verify_auth_version(binary, work)
    evidence = {"scope": "DISPOSABLE_LOCAL_REAL_GOTRUE_CANONICAL_OWNER_NOT_PRODUCTION",
        "status": "FAIL", "auth_version": AUTH_VERSION, "auth_upstream_commit": AUTH_COMMIT,
        "auth_archive_sha256": AUTH_ARCHIVE_SHA256, "auth_executable_sha256": _sha(binary.read_bytes()),
        "engine_manifest_sha256": manifest_sha256, "external_services_used": False,
        "smtp_external_used": False, "user_jwt_fabricated": False, "credentials_recorded": False,
        "cleanup": {"processes": False, "database": True, "logins": True}}
    processes, logins = [], []
    new_dsn, database, stage = None, None, "create_database"
    old_stack = homologacao_stack.BINARIO_PGRST, homologacao_stack.PORTA_PGRST
    old_logging = logging.root.manager.disable
    logging.disable(logging.CRITICAL)
    try:
        import psycopg
        from psycopg import sql
        new_dsn, database = sql_harness.criar_banco_descartavel(dsn)
        auth_login, rest_login = "auth_login_" + uuid.uuid4().hex, "auth_rest_" + uuid.uuid4().hex
        auth_password, rest_password, secret = (secrets.token_urlsafe(48) for _ in range(3))
        stage = "bootstrap_roles"
        with psycopg.connect(new_dsn, autocommit=True) as connection:
            connection.execute(sql_harness.PREAMBULO_ANTES_AUTH)
            for name, password in ((auth_login, auth_password), (rest_login, rest_password)):
                connection.execute(sql.SQL("create role {} login noinherit password {}").format(sql.Identifier(name), sql.Literal(password)))
                logins.append(name)
            connection.execute(sql.SQL("alter schema auth owner to {}").format(sql.Identifier(auth_login)))
            connection.execute(sql.SQL("grant authenticator to {}").format(sql.Identifier(rest_login)))
        auth_port, rest_port, gateway_port = _available_port(), _available_port(), _available_port()
        _check(len({auth_port, rest_port, gateway_port}) == 3, "unique_loopback_ports")
        auth_env = auth_environment(database_url=_database_url(admin_config, database=database, user=auth_login,
            password=auth_password), secret=secret, port=auth_port, gateway_port=gateway_port)
        stage = "official_gotrue_migrations"
        migrated = subprocess.run([str(binary), "migrate"], env=auth_env, cwd=work, stdout=subprocess.DEVNULL,
                                  stderr=subprocess.DEVNULL, timeout=90, check=False)
        _check(migrated.returncode == 0, stage)
        stage = "canonical_app_migrations"
        with psycopg.connect(new_dsn, autocommit=True) as connection:
            schema = sql_harness.preparar(connection, auth_real=True)
        evidence["auth_migration_required"] = sql_harness.AUTH_MIGRACAO_EXIGIDA
        evidence["app_migration_count"] = len(schema["migracoes"]) + len(schema["em_ensaio"])
        stage = "start_services"
        processes.append(subprocess.Popen([str(binary), "serve"], cwd=work, env=auth_env,
                                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL))
        homologacao_stack._esperar_porta(auth_port, processo=processes[-1])
        health = _http_json(f"http://127.0.0.1:{auth_port}/health")
        _check(health.get("version") in {AUTH_VERSION, AUTH_VERSION[1:]} and health.get("name") == "GoTrue", "real_gotrue_health")
        homologacao_stack.BINARIO_PGRST, homologacao_stack.PORTA_PGRST = str(postgrest), rest_port
        rest_dsn = _database_url(admin_config, database=database, user=rest_login, password=rest_password)
        with _environment(_child_environment()):
            processes.append(homologacao_stack.subir_postgrest(rest_dsn, secret))
        processes.append(subprocess.Popen([sys.executable, str(ROOT / "scripts/gateway_supabase.py"),
            "--porta", str(gateway_port), "--destino", f"http://127.0.0.1:{rest_port}",
            "--destino-auth", f"http://127.0.0.1:{auth_port}"], cwd=work, env=_child_environment(),
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL))
        homologacao_stack._esperar_porta(gateway_port, processo=processes[-1])
        # Only infrastructure keys are minted locally. Every user's JWT comes
        # from a password exchange with the official GoTrue above.
        public = homologacao_stack.cunhar_jwt("anon", secret, validade_s=600)
        server = homologacao_stack.cunhar_jwt("service_role", secret, validade_s=600)
        environment = _child_environment()
        environment.update({"SUPABASE_URL": f"http://127.0.0.1:{gateway_port}", "SUPABASE_KEY": public,
            "SUPABASE_SERVICE_KEY": server, "GOVDOCS_EXIGIR_CREDENCIAL_SERVIDOR": "1",
            "GOVDOCS_EXIGIR_SUPABASE_AUTH": "1", "GOVDOCS_SONDAR_CREDENCIAL": "1", "GOVDOCS_AMBIENTE": "homologacao"})
        stage = "real_auth_owner_proofs"
        with _environment(environment):
            from src import db
            db._cliente.clear()
            db._sonda_bem_sucedida.clear()
            try:
                _proof(database_dsn=new_dsn, config={"node": node, "bundle": bundle, "manifest_sha256": manifest_sha256},
                       secret=secret, gateway_port=gateway_port, server_key=server, public_key=public, evidence=evidence)
            finally:
                db._cliente.clear()
                db._sonda_bem_sucedida.clear()
        evidence["status"] = "PASS_REAL_AUTH_LOCAL"
    except Exception as error:
        evidence.update(_failure_record(error, fallback=stage))
    finally:
        evidence["cleanup"]["processes"] = _stop_children(processes)
        homologacao_stack.BINARIO_PGRST, homologacao_stack.PORTA_PGRST = old_stack
        if database is not None:
            try:
                sql_harness.descartar_banco(dsn, database)
                evidence["cleanup"]["database"] = not homologacao_local._existe(dsn, database)
            except Exception:
                evidence["cleanup"]["database"] = False
        if logins:
            cleanup_roles = True
            try:
                with psycopg.connect(dsn, autocommit=True) as connection:
                    for name in reversed(logins):
                        try:
                            connection.execute(sql.SQL("drop role {}").format(sql.Identifier(name)))
                        except Exception:
                            cleanup_roles = False
                    remaining = connection.execute("select count(*) from pg_roles where rolname=any(%s)", (logins,)).fetchone()[0]
                    evidence["cleanup"]["logins"] = cleanup_roles and remaining == 0
            except Exception:
                evidence["cleanup"]["logins"] = False
        else:
            evidence["cleanup"]["logins"] = True
        logging.disable(old_logging)
        if not all(evidence["cleanup"].values()):
            evidence["status"] = "FAIL"
            evidence["cleanup_failed"] = True
    (work / "auth-real.json").write_text(json.dumps(evidence, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return evidence


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dsn", required=True)
    parser.add_argument("--auth-archive", type=Path, required=True)
    parser.add_argument("--postgrest", type=Path, required=True)
    parser.add_argument("--node", type=Path, required=True)
    parser.add_argument("--bundle", type=Path, required=True)
    parser.add_argument("--manifest-sha256", required=True)
    parser.add_argument("--work-dir", type=Path, required=True)
    args = parser.parse_args()
    try:
        evidence = executar(dsn=args.dsn, archive=args.auth_archive, postgrest=args.postgrest,
            node=args.node, bundle=args.bundle, manifest_sha256=args.manifest_sha256, work=args.work_dir)
    except Exception as error:
        print(json.dumps({"status": "FAIL_PREFLIGHT", **_failure_record(error, fallback="preflight")}))
        return 1
    print(json.dumps({"status": evidence["status"], "checks": len(evidence.get("checks", {})), "cleanup": evidence["cleanup"],
                      **{key: evidence[key] for key in ("failed_stage", "error_type") if key in evidence}}))
    return 0 if evidence["status"] == "PASS_REAL_AUTH_LOCAL" else 1


if __name__ == "__main__":
    raise SystemExit(main())
