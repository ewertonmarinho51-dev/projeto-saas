"""Execute existing HTTP containment proofs on a disposable local PostgreSQL.

No GoTrue/Storage, remote secrets or alternative document persistence. Uses the
canonical schema and rehearsal helpers. The caller starts PostgreSQL with vector.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import secrets
import subprocess
import sys
import uuid

import homologacao_local
import homologacao_stack
from ensaio_local import descartar_banco, exigir_dsn_local

ROOT = Path(__file__).resolve().parent.parent
HTTP_SELECTION = " or ".join([
    "test_catalogo_", "test_anon_nao_le_tabela_privada",
    "test_anon_nao_escreve_no_objeto_descartavel", "test_anon_nao_executa_rpc",
    "test_funcao_nova_nasce_fechada", "test_servidor_continua_operando",
    "test_storage_sem_bucket_e_nao_aplicavel",
])


def executar(*, dsn: str, postgrest: Path, work: Path, pg_bin: Path | None = None) -> int:
    exigir_dsn_local(dsn)  # Must precede database/process/file mutations.
    postgrest = postgrest.resolve(strict=True)
    if not postgrest.is_file():
        raise ValueError("Explicit PostgREST executable required")
    if pg_bin is not None and not pg_bin.is_dir():
        raise ValueError("PostgreSQL binary directory is missing")
    work.mkdir(parents=True, exist_ok=True)
    # Never reuse an existing database or accept a caller-supplied SQL identifier.
    database = "http_qa_" + uuid.uuid4().hex
    if homologacao_local._existe(dsn, database):
        raise RuntimeError("Fresh rehearsal database required")
    processes = []
    login = "http_login_" + uuid.uuid4().hex
    login_created = False
    previous = (homologacao_stack.BINARIO_PGRST, homologacao_stack.PORTA_PGRST,
                homologacao_stack.PORTA_ADAPTADOR, os.environ.get("PATH", ""))
    try:
        report = homologacao_local.montar(dsn, banco=database)
        if report.get("reaproveitado"):
            raise RuntimeError("Refusing a reused rehearsal database")
        homologacao_stack.BINARIO_PGRST = str(postgrest)
        homologacao_stack.PORTA_PGRST = 55440
        homologacao_stack.PORTA_ADAPTADOR = 55441
        if pg_bin is not None:
            os.environ["PATH"] = str(pg_bin.resolve()) + os.pathsep + previous[3]
        secret = secrets.token_urlsafe(48)
        # An ephemeral login inherits SET ROLE membership through the canonical
        # authenticator. Do not replace the existing authenticator's password.
        import psycopg
        from psycopg import sql
        password = secrets.token_urlsafe(48)
        with psycopg.connect(dsn, autocommit=True) as admin:
            admin.execute(sql.SQL("create role {} login noinherit password {}").format(
                sql.Identifier(login), sql.Literal(password)))
            login_created = True
            admin.execute(sql.SQL("grant authenticator to {}").format(sql.Identifier(login)))
        connection = psycopg.conninfo.conninfo_to_dict(report["dsn"])
        connection.update(user=login, password=password)
        app_dsn = psycopg.conninfo.make_conninfo(**connection)
        processes.append(homologacao_stack.subir_postgrest(app_dsn, secret))
        processes.append(homologacao_stack.subir_adaptador())
        environment = {k: v for k, v in os.environ.items()
                       if not k.startswith("SUPABASE_")
                       and not k.startswith("GOVDOCS_ENSAIO_")}
        environment.update({
            "GOVDOCS_ENSAIO_URL": "http://127.0.0.1:55441",
            "GOVDOCS_ENSAIO_PROJETO": "loopback",
            "GOVDOCS_ENSAIO_ANON_KEY": homologacao_stack.cunhar_jwt("anon", secret),
            "GOVDOCS_ENSAIO_SECRET_KEY": homologacao_stack.cunhar_jwt("service_role", secret),
            "GOVDOCS_ENSAIO_CLIENTE_HTTP_MINIMO": "1",
            "PYTHONUTF8": "1",
        })
        result = subprocess.run([
            sys.executable, "-m", "pytest", "tests/test_seguranca_contencao.py",
            "-k", HTTP_SELECTION, "-q", "--tb=short",
            "--basetemp=" + str(work / "tmp"),
            "-o", "cache_dir=" + str(work / "cache"),
            "--junitxml=" + str(work / "http.xml"),
        ], cwd=ROOT, env=environment, check=False)
        print(json.dumps({"scope": "LOCAL_HTTP_NOT_GOTRUE_NOT_WORDCRAFT_PERSISTENCE",
                          "exit_code": result.returncode}))
        return result.returncode
    finally:
        for process in reversed(processes):
            homologacao_stack._encerrar(process)
        (homologacao_stack.BINARIO_PGRST, homologacao_stack.PORTA_PGRST,
         homologacao_stack.PORTA_ADAPTADOR, os.environ["PATH"]) = previous
        descartar_banco(dsn, database)
        if login_created:
            with psycopg.connect(dsn, autocommit=True) as admin:
                admin.execute(sql.SQL("drop role {}").format(sql.Identifier(login)))
        if homologacao_local._existe(dsn, database):
            raise RuntimeError("Rehearsal database cleanup failed")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dsn", required=True)
    parser.add_argument("--postgrest", type=Path, required=True)
    parser.add_argument("--work-dir", type=Path, required=True)
    parser.add_argument("--pg-bin", type=Path)
    args = parser.parse_args()
    return executar(dsn=args.dsn, postgrest=args.postgrest,
                    work=args.work_dir.resolve(), pg_bin=args.pg_bin)


if __name__ == "__main__":
    raise SystemExit(main())
