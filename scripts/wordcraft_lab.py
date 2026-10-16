"""Reproduce the synthetic WordCraft slice on a private loopback database.

No hosted Supabase, GoTrue, provider calls, deployment or production flags.
Reuses the canonical SQL rehearsal and HTTP gateway. Restart preserves the lab's
own database; it never migrates or resets a reused database silently.
"""
from __future__ import annotations

import argparse
from dataclasses import dataclass, field, replace
import hashlib
import json
import os
from pathlib import Path
import re
import secrets
import subprocess
import sys
import threading
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit
from uuid import uuid4, UUID

import homologacao_local
import homologacao_stack as stack
from ensaio_local import descartar_banco, exigir_dsn_local, migracoes_do_schema, sequencia_em_ensaio
from wordcraft_local_assets import MARKER, ROOT, WORK_ROOT, safe_name
import wordcraft_notices

CASES = ("01-texto-listas-links", "02-tabela-210-itens", "03-timbrado-assinaturas")
NOTICE_NAMES = frozenset(
    ["wordcraft/" + Path(name).name for name in wordcraft_notices.UPSTREAM_FILES]
    + ["wordcraft/fonts/" + name for name in wordcraft_notices.UPSTREAM_FONTS]
    + ["epaint_default_fonts/" + name for name in json.loads(
        (wordcraft_notices.FONT_SOURCE / "PROVENANCE.json").read_text(encoding="utf-8"))["files"]])


@dataclass(frozen=True)
class Config:
    dsn: str = field(repr=False)
    lab: Path
    corpus: Path
    node: Path
    postgrest: Path
    manifest_sha256: str
    cluster_data: Path
    pg_bin: Path | None = None
    app_port: int = 8884
    rest_port: int = 55450
    gateway_port: int = 55451


def validate(config: Config) -> dict:
    """Reject ambiguous config before writes, then validate with the native IPC."""
    exigir_dsn_local(config.dsn)
    # libpq can take an effective address/service/options from the environment
    # even when a URI names localhost. No inherited PG configuration is part of
    # this isolated lab's contract; never print its values.
    if any(name.upper().startswith("PG") for name in os.environ):
        raise ValueError("Inherited PostgreSQL configuration is not allowed in the isolated lab")
    address = urlsplit(config.dsn)
    query = parse_qsl(address.query, keep_blank_values=True)
    if (address.scheme not in {"postgres", "postgresql"} or address.hostname != "127.0.0.1"
            or not address.username or not address.path.strip("/") or address.fragment
            or any(k not in {"connect_timeout", "sslmode"} for k, _ in query)
            or len({k for k, _ in query}) != len(query)):
        raise ValueError("Only an explicit IPv4 loopback PostgreSQL URI is accepted")
    ports = (config.app_port, config.rest_port, config.gateway_port)
    if len(set(ports)) != 3 or any(type(p) is not int or not 1024 <= p <= 65535 for p in ports):
        raise ValueError("Three distinct unprivileged loopback ports are required")
    lab = config.lab.resolve(strict=True)
    if (not lab.is_relative_to(WORK_ROOT.resolve()) or lab.is_relative_to(ROOT.resolve())
            or (lab / ".wordcraft-local-qa").read_text(encoding="utf-8") != MARKER):
        raise ValueError("Explicit isolated lab marker required")
    if not re.fullmatch(r"[0-9a-f]{64}", config.manifest_sha256):
        raise ValueError("Trusted manifest hash required")
    assets = lab / "static/wordcraft"
    if not assets.resolve(strict=True).is_relative_to(lab):
        raise ValueError("Static namespace escaped the isolated lab")
    cluster = config.cluster_data.resolve(strict=True)
    if (not cluster.is_relative_to(WORK_ROOT.resolve()) or cluster.is_relative_to(ROOT.resolve())
            or (cluster / ".wordcraft-local-qa").read_text(encoding="utf-8") != MARKER
            or not (cluster / "PG_VERSION").is_file()):
        raise ValueError("A marked disposable PostgreSQL cluster is required")
    if (assets / "qa-manifest.json").stat().st_size > 1024 * 1024:
        raise ValueError("Manifest exceeds byte bound")
    raw = (assets / "qa-manifest.json").read_bytes()
    if hashlib.sha256(raw).hexdigest() != config.manifest_sha256:
        raise ValueError("Staged manifest hash differs")
    manifest = json.loads(raw)
    if manifest.get("status") != "INTERNAL_LOCAL_QA_ONLY_NOT_DEPLOY_APPROVED":
        raise ValueError("Only CI's internal QA artifact is accepted")
    files = manifest.get("files", [])
    urls = {}
    if not 2 <= len(files) <= 100:
        raise ValueError("Unexpected asset inventory")
    total = 0
    seen = set()
    for item in files:
        name = safe_name(item["path"])
        if (name in seen or type(item["bytes"]) is not int or not 0 < item["bytes"] <= 80 * 1024 * 1024
                or not re.fullmatch(r"[0-9a-f]{64}", item["sha256"])):
            raise ValueError("Ambiguous or excessive engine asset")
        seen.add(name)
        total += item["bytes"]
        if total > 200 * 1024 * 1024:
            raise ValueError("Engine asset total exceeds byte bound")
        path = (assets / name).resolve(strict=True)
        if not path.is_relative_to(assets.resolve()) or not path.is_file():
            raise ValueError("Asset escaped the isolated namespace")
        if path.stat().st_size != item["bytes"] or hashlib.sha256(path.read_bytes()).hexdigest() != item["sha256"]:
            raise ValueError("Staged asset differs")
        if "/" not in name and path.suffix in {".js", ".wasm"}:
            if path.suffix in urls:
                raise ValueError("Ambiguous engine entry points")
            urls[path.suffix] = "/app/static/wordcraft/" + name
    if set(urls) != {".js", ".wasm"}:
        raise ValueError("Explicit JS/WASM entry points required")
    notice_manifest = assets / "notices/manifest.json"
    if notice_manifest.stat().st_size > 1024 * 1024:
        raise ValueError("Notice manifest exceeds byte bound")
    notices = json.loads(notice_manifest.read_bytes())
    if (notices.get("status") != "UPSTREAM_AND_FONT_NOTICES_VERIFIED"
            or notices.get("upstream_commit") != manifest.get("upstream_commit")
            or len(notices.get("files", [])) != len(NOTICE_NAMES)
            or {item["path"] for item in notices["files"]} != NOTICE_NAMES):
        raise ValueError("Pinned public notice inventory differs")
    public_files = {"qa-manifest.json", "notices/manifest.json", *seen}
    for item in notices["files"]:
        relative = "notices/" + safe_name(item["path"])
        path = (assets / relative).resolve(strict=True)
        if not path.is_relative_to(assets.resolve()) or not path.is_file() or path.stat().st_size > 200_000:
            raise ValueError("Notice escaped its bounded namespace")
        data = path.read_bytes()
        if b"\0" in data or hashlib.sha256(data).hexdigest() != item["sha256_canonical_lf"]:
            raise ValueError("Notice digest differs")
        data.decode("utf-8")
        public_files.add(relative)
    if any(path.is_file() and path.relative_to(assets).as_posix() not in public_files for path in assets.rglob("*")):
        raise ValueError("Uninventoried file in public namespace")
    for binary in (config.node, config.postgrest):
        if not binary.is_absolute() or not binary.is_file():
            raise ValueError("Explicit installed runtime executables required")
    if config.pg_bin is not None and not config.pg_bin.is_dir():
        raise ValueError("PostgreSQL binary directory missing")
    # These checkpoints were emitted by the verified native corpus run. Validate
    # them again with the pinned engine before creating even a synthetic user.
    sys.path.insert(0, str(ROOT))
    from src.wordcraft_native import validar
    for case in CASES:
        payload = (config.corpus / case / "checkpoint.json").read_bytes()
        validar(payload, node=config.node, bundle=assets, manifest_sha256=config.manifest_sha256)
    return {"module_url": urls[".js"], "wasm_url": urls[".wasm"], "public_files": sorted(public_files),
            "host": "127.0.0.1", "port": address.port or 5432}


def pinned_dsn(dsn: str) -> str:
    """Only call after validate; pin libpq's actual address and port explicitly."""
    address = urlsplit(dsn)
    query = parse_qsl(address.query, keep_blank_values=True)
    return urlunsplit((address.scheme, address.netloc, address.path,
                      urlencode([*query, ("hostaddr", "127.0.0.1"), ("port", str(address.port or 5432))]), ""))


def require_disposable_cluster(config: Config, plan: dict) -> None:
    """Read-only identity check before canonical bootstrap can change any roles."""
    import psycopg
    with psycopg.connect(config.dsn) as connection:
        row = connection.execute("select current_setting('data_directory'), current_setting('listen_addresses'), host(inet_server_addr()), inet_server_port()").fetchone()
        if (row is None or Path(row[0]).resolve() != config.cluster_data.resolve()
                or row[1] != "127.0.0.1" or row[2:] != ("127.0.0.1", plan["port"])):
            raise ValueError("PostgreSQL is not the marked disposable loopback cluster")


def wait_for_stop(process, command_stream=None) -> int:
    """`stop` on stdin gives API-driven QA a graceful path through cleanup."""
    stopped = threading.Event()
    stream = sys.stdin if command_stream is None else command_stream
    def read_commands():
        try:
            for line in stream:
                if line.strip() == "stop":
                    stopped.set()
                    return
        except (OSError, ValueError):
            return
    threading.Thread(target=read_commands, daemon=True).start()
    while process.poll() is None:
        if stopped.wait(0.25):
            return 0
    return process.returncode


def schema_hash() -> str:
    digest = hashlib.sha256()
    for migration in [*migracoes_do_schema(), *sequencia_em_ensaio()]:
        digest.update(migration.name.encode())
        digest.update(migration.read_bytes().replace(b"\r\n", b"\n"))
    return digest.hexdigest()


def prepare(config: Config, plan: dict) -> dict:
    """Own only a fresh random DB, or verify the exact DB owned by this lab."""
    import psycopg
    from psycopg import sql
    from psycopg.types.json import Jsonb
    state_path = config.lab / "qa-state.json"
    fingerprint = schema_hash()
    if state_path.exists():
        state = json.loads(state_path.read_text(encoding="utf-8"))
        if (set(state) != {"schema", "id", "database", "host", "port", "schema_hash", "identity"}
                or state["schema"] != "gc-wordcraft-lab/v1"
                or str(UUID(state["id"])) != state["id"]
                or not re.fullmatch(r"wc_lab_[0-9a-f]{32}", state["database"])
                or (state["host"], state["port"], state["schema_hash"]) != (plan["host"], plan["port"], fingerprint)):
            raise ValueError("Lab state or schema changed; use a fresh marked lab")
        database_dsn = homologacao_local._dsn_do_banco(config.dsn, state["database"])
        with psycopg.connect(database_dsn) as connection:
            tag = connection.execute("select shobj_description(oid,'pg_database') from pg_database where datname=current_database()").fetchone()
            if tag != ("govconnect-wordcraft-lab:" + state["id"],):
                raise ValueError("Database ownership marker differs")
            identity = state["identity"]
            row = connection.execute("select tenant_id,secretaria_id,auth_user_id,ativo from public.usuarios where id=%s", (identity["id"],)).fetchone()
            if not row or not row[3] or tuple(map(str, row[:3])) != tuple(identity[k] for k in ("tenant_id", "secretaria_id", "auth_user_id")):
                raise ValueError("Synthetic profile changed; never reset a reused lab")
        return state
    lab_id, database = str(uuid4()), "wc_lab_" + uuid4().hex
    if homologacao_local._existe(config.dsn, database):
        raise RuntimeError("Fresh database name required")
    try:
        report = homologacao_local.montar(config.dsn, banco=database)
        if report.get("reaproveitado"):
            raise RuntimeError("Refusing an existing database")
        with psycopg.connect(report["dsn"]) as connection:
            connection.execute(sql.SQL("comment on database {} is {}").format(sql.Identifier(database), sql.Literal("govconnect-wordcraft-lab:" + lab_id)))
            tenant = connection.execute("insert into public.tenants (slug,nome,uf) values (%s,'Laboratório sintético','PA') returning id", ("wordcraft-lab-" + uuid4().hex,)).fetchone()[0]
            secretary = connection.execute("insert into public.secretarias (tenant_id,nome,sigla) values (%s,'Ensaio','QA') returning id", (tenant,)).fetchone()[0]
            metadata = {"tenant_id": str(tenant), "secretaria_id": str(secretary), "papel": "usuario"}
            auth_id = connection.execute("insert into auth.users (email,raw_app_meta_data) values (%s,%s) returning id", (uuid4().hex + "@example.invalid", Jsonb(metadata))).fetchone()[0]
            user_id = connection.execute("insert into public.usuarios (nome,login,senha_hash,papel,tenant_id,secretaria_id,auth_user_id) values ('Operador sintético',%s,'NO_PASSWORD_LOGIN','usuario',%s,%s,%s) returning id", (uuid4().hex, tenant, secretary, auth_id)).fetchone()[0]
            processes = {}
            for case in CASES:
                process = connection.execute("insert into public.processos (orgao,objeto,tenant_id,secretaria_id,auth_user_id,documentos) values ('Laboratório',%s,%s,%s,%s,%s) returning id", (case, tenant, secretary, auth_id, Jsonb({"dfd": "Original sintético preservado", "tr": "# Fonte legada sintética\n\nImportação Markdown com **acentuação** e original preservado.\n\n1. Material sintético autorizado para o ensaio."}))).fetchone()[0]
                processes[case] = str(process)
        state = {"schema": "gc-wordcraft-lab/v1", "id": lab_id, "database": database,
                 "host": plan["host"], "port": plan["port"], "schema_hash": fingerprint,
                 "identity": {"id": str(user_id), "auth_user_id": str(auth_id), **metadata, "processes": processes}}
        with state_path.open("x", encoding="utf-8") as output:
            json.dump(state, output, ensure_ascii=False, indent=2)
        return state
    except BaseException:
        # Only the fresh random database allocated in this function is disposable.
        descartar_banco(config.dsn, database)
        raise



def serve(config: Config) -> int:
    config = replace(config, lab=config.lab.resolve(strict=True), corpus=config.corpus.resolve(strict=True),
                     cluster_data=config.cluster_data.resolve(strict=True))
    plan = validate(config)
    if any(not stack._porta_livre(port) for port in (config.app_port, config.rest_port, config.gateway_port)):
        raise ValueError("Requested lab port occupied; no existing process touched")
    config = replace(config, dsn=pinned_dsn(config.dsn))
    require_disposable_cluster(config, plan)
    state = prepare(config, plan)
    import psycopg
    from psycopg import sql
    identity = state["identity"]
    database_dsn = homologacao_local._dsn_do_banco(config.dsn, state["database"])
    secret, password = secrets.token_urlsafe(48), secrets.token_urlsafe(48)
    login = "wc_lab_login_" + uuid4().hex
    processes = []
    created_login = False
    previous = (stack.BINARIO_PGRST, stack.PORTA_PGRST, stack.PORTA_ADAPTADOR, os.environ.get("PATH", ""))
    try:
        with psycopg.connect(config.dsn, autocommit=True) as admin:
            admin.execute(sql.SQL("create role {} login noinherit password {}").format(sql.Identifier(login), sql.Literal(password)))
            created_login = True
            admin.execute(sql.SQL("grant authenticator to {}").format(sql.Identifier(login)))
        connection = psycopg.conninfo.conninfo_to_dict(database_dsn)
        connection.update(user=login, password=password)
        stack.BINARIO_PGRST, stack.PORTA_PGRST, stack.PORTA_ADAPTADOR = str(config.postgrest), config.rest_port, config.gateway_port
        if config.pg_bin is not None:
            os.environ["PATH"] = str(config.pg_bin.resolve()) + os.pathsep + previous[3]
        processes.append(stack.subir_postgrest(psycopg.conninfo.make_conninfo(**connection), secret))
        processes.append(stack.subir_adaptador())
        user_claims = {"sub": identity["auth_user_id"], "app_metadata": {k: identity[k] for k in ("tenant_id", "secretaria_id", "papel")}}
        environment = {k: os.environ[k] for k in ("SystemRoot", "WINDIR", "TEMP", "TMP", "PATH", "USERPROFILE", "APPDATA", "LOCALAPPDATA", "PYTHONPATH") if k in os.environ}
        environment.update({"SUPABASE_URL": f"http://127.0.0.1:{config.gateway_port}",
            "SUPABASE_KEY": stack.cunhar_jwt("anon", secret),
            "SUPABASE_SERVICE_KEY": stack.cunhar_jwt("service_role", secret),
            "GOVDOCS_WORDCRAFT_QA_ACCESS_TOKEN": stack.cunhar_jwt("authenticated", secret, **user_claims),
            "GOVDOCS_WORDCRAFT_LAB": json.dumps({"lab": str(config.lab), "corpus": str(config.corpus), "node": str(config.node), "manifest_sha256": config.manifest_sha256, "origin": f"http://127.0.0.1:{config.app_port}", "identity": identity, **plan}),
            "STREAMLIT_BROWSER_GATHER_USAGE_STATS": "false", "STREAMLIT_SERVER_HEADLESS": "true", "PYTHONUTF8": "1"})
        processes.append(subprocess.Popen([sys.executable, "-m", "uvicorn", "server:app", "--host", "127.0.0.1", "--port", str(config.app_port), "--no-access-log"], cwd=ROOT / "integrations/wordcraft/lab", env=environment, stdin=subprocess.DEVNULL))
        stack._esperar_porta(config.app_port, processo=processes[-1])
        print(json.dumps({"scope": "SYNTHETIC_LOOPBACK_ONLY_NO_GOTRUE", "url": f"http://127.0.0.1:{config.app_port}", "database_preserved_for_restart": True}), flush=True)
        return wait_for_stop(processes[-1])
    finally:
        for process in reversed(processes):
            stack._encerrar(process)
        stack.BINARIO_PGRST, stack.PORTA_PGRST, stack.PORTA_ADAPTADOR, os.environ["PATH"] = previous
        if created_login:
            with psycopg.connect(config.dsn, autocommit=True) as admin:
                admin.execute(sql.SQL("drop role {}").format(sql.Identifier(login)))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("dsn", "manifest-sha256"):
        parser.add_argument("--" + name, required=True)
    for name in ("lab", "corpus", "node", "postgrest", "cluster-data"):
        parser.add_argument("--" + name, type=Path, required=True)
    parser.add_argument("--pg-bin", type=Path)
    for name, default in (("app-port", 8884), ("rest-port", 55450), ("gateway-port", 55451)):
        parser.add_argument("--" + name, type=int, default=default)
    config = Config(**vars(parser.parse_args()))
    try:
        return serve(config)
    except KeyboardInterrupt:
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
