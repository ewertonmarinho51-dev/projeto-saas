"""Exact institutional migration on fresh local DBs; no native validity claim."""
from contextlib import contextmanager
import hashlib
import json
import os
from pathlib import Path
import sys
from uuid import uuid4

import pytest

from src.documentos_editor import _snapshot_bytes
from tests.conftest import exigir_ensaio_sql
from tests.test_documentos_editor_sql import role, seed_scenario, commit as g2_commit

MIGRATION = "20261015124841_documentos_editor_snapshot_institucional.sql"


@contextmanager
def database(*, upgraded=True):
    exigir_ensaio_sql()
    import psycopg
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
    import ensaio_local as harness
    base = os.environ["GOVDOCS_ENSAIO_PG_DSN"]
    harness.exigir_dsn_local(base)
    dsn, name = harness.criar_banco_descartavel(base)
    try:
        with psycopg.connect(dsn, autocommit=True) as connection:
            original_sequence = harness.SEQUENCIA_EM_ENSAIO
            try:
                if not upgraded:
                    harness.SEQUENCIA_EM_ENSAIO = tuple(name for name in original_sequence if name != MIGRATION)
                harness.preparar(connection)
            finally:
                harness.SEQUENCIA_EM_ENSAIO = original_sequence
            if upgraded and MIGRATION not in original_sequence:
                connection.execute((harness.MIGRACOES / MIGRATION).read_text(encoding="utf-8"))
            yield connection, harness.MIGRACOES / MIGRATION
    finally:
        harness.descartar_banco(base, name)


@pytest.fixture(scope="module")
def institutional_db():
    with database() as (connection, _):
        yield connection


@pytest.fixture
def scenario(institutional_db):
    return seed_scenario(institutional_db)


def snapshot(scenario, *, revision=1, header="Identidade anterior"):
    metadata = scenario["owner"]["app_metadata"]
    return _snapshot_bytes({"schema": "gc-wordcraft-institutional/v1", "phase": "draft_reference",
        "application": "reference_only", "document_id": str(scenario["doc"]), "processo_id": str(scenario["process"]),
        "tenant_id": metadata["tenant_id"], "secretaria_id": metadata["secretaria_id"], "doc_key": "dfd",
        "captured_for_revision": revision, "reference_date": "2026-01-20", "identity": {"cabecalho": header},
        "signatories": [], "portaria": None, "signature_block": ""})


def commit(connection, scenario, *, expected=0, operation=None, payload=b"opaque institutional SQL fixture",
           institutional=None, restored=None):
    from psycopg.types.json import Jsonb
    mode = "initial"
    if expected:
        with connection.cursor() as cursor:
            cursor.execute("select block_index,institutional_snapshot from public.documentos_editor_revisoes "
                           "where document_id=%s and revision=%s", (scenario["doc"], expected))
            base = cursor.fetchone()
            mode = "reconciled" if base[0] is not None else "rebuilt_missing_index"
            cursor.execute("select institutional_snapshot from public.documentos_editor_revisoes "
                           "where document_id=%s and revision=%s", (scenario["doc"], restored or expected))
            source = cursor.fetchone()
            if institutional is None and source and source[0] is not None:
                institutional = bytes(source[0])
    if institutional is None:
        institutional = snapshot(scenario, revision=expected + 1)
    digest = hashlib.sha256(payload).hexdigest()
    index = json.dumps({"schema": "gc-wordcraft-block-index/v1", "document_id": str(scenario["doc"]),
        "revision": expected + 1, "content_hash": digest, "engine_manifest_sha256": "a" * 64,
        "blocos": [], "invalidacoes": [], "areas_nao_enderecaveis": []}, sort_keys=True, separators=(",", ":")).encode()
    params = (scenario["doc"], scenario["process"], "dfd", expected, operation or scenario["operation"], payload, digest,
        Jsonb(scenario["owner"]), "a" * 64, index, hashlib.sha256(index).hexdigest(), mode,
        None, None, None, restored, institutional, hashlib.sha256(institutional).hexdigest())
    with role(connection, "service_role") as cursor:
        cursor.execute("select * from public.documento_editor_checkpoint(" + ",".join(["%s"] * 18) + ")", params)
        result = cursor.fetchone()
        cursor.execute("select auth.jwt()->>'role'")
        assert cursor.fetchone() == ("service_role",)
        return result


def test_recorded_reference_survives_registry_change_and_never_promotes_approval(institutional_db, scenario):
    before = snapshot(scenario)
    first = commit(institutional_db, scenario, institutional=before)
    institutional_db.execute("update public.secretarias set cabecalho='OUTRO TIMBRADO' where id=%s",
                             (scenario["owner"]["app_metadata"]["secretaria_id"],))
    second = commit(institutional_db, scenario, expected=1, operation=uuid4())
    assert first[11] == second[11] == hashlib.sha256(before).hexdigest()
    rows = institutional_db.execute("select institutional_snapshot from public.documentos_editor_revisoes "
        "where document_id=%s order by revision", (scenario["doc"],)).fetchall()
    assert [bytes(row[0]) for row in rows] == [before, before]
    assert institutional_db.execute("select status from public.documentos_editor where id=%s", (scenario["doc"],)).fetchone() == ("rascunho",)
    assert institutional_db.execute("select aprovados from public.processos where id=%s", (scenario["process"],)).fetchone() == ([],)


def test_retry_and_autosave_cannot_replace_the_institutional_history(institutional_db, scenario):
    import psycopg
    before = snapshot(scenario)
    commit(institutional_db, scenario, institutional=before)
    assert commit(institutional_db, scenario, institutional=before)[4] is True
    for expected, operation in ((0, scenario["operation"]), (1, uuid4())):
        with pytest.raises(psycopg.errors.SerializationFailure):
            commit(institutional_db, scenario, expected=expected, operation=operation,
                   institutional=snapshot(scenario, header="OUTRA IDENTIDADE"))
    assert institutional_db.execute("select count(*) from public.documentos_editor_revisoes where document_id=%s", (scenario["doc"],)).fetchone() == (1,)


def test_institutional_reference_is_private_and_immutable_even_with_server_role(institutional_db, scenario):
    import psycopg
    commit(institutional_db, scenario)
    for name in ("authenticated", "service_role"):
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            with role(institutional_db, name, scenario["owner"] if name == "authenticated" else None) as cursor:
                cursor.execute("update public.documentos_editor_revisoes set institutional_snapshot='changed'::bytea")
    with role(institutional_db, "authenticated", scenario["other"]) as cursor:
        cursor.execute("select institutional_snapshot from public.documentos_editor_revisoes where document_id=%s", (scenario["doc"],))
        assert cursor.fetchall() == []


@pytest.mark.parametrize("change", ["approval", "tenant", "document", "revision"])
def test_misbound_or_approved_snapshot_claim_is_rejected_atomically(institutional_db, scenario, change):
    import psycopg
    value = json.loads(snapshot(scenario))
    field, replacement = {"approval": ("phase", "approved"), "tenant": ("tenant_id", str(uuid4())),
        "document": ("document_id", str(uuid4())), "revision": ("captured_for_revision", 99)}[change]
    value[field] = replacement
    error = psycopg.errors.InsufficientPrivilege if change == "tenant" else psycopg.errors.InvalidParameterValue
    with pytest.raises(error):
        commit(institutional_db, scenario, institutional=_snapshot_bytes(value))
    assert institutional_db.execute("select count(*) from public.documentos_editor where id=%s", (scenario["doc"],)).fetchone() == (0,)


def test_old_signature_is_removed_and_new_one_is_private(institutional_db):
    rows = institutional_db.execute("select pronargs,prosecdef,has_function_privilege('authenticated',oid,'execute'),"
        "has_function_privilege('anon',oid,'execute'),has_function_privilege('service_role',oid,'execute') "
        "from pg_proc where pronamespace='public'::regnamespace and proname='documento_editor_checkpoint'").fetchall()
    assert rows == [(18, False, False, False, True)]


def test_upgrade_does_not_invent_history_and_restore_unknown_context_records_only_current_reference():
    with database(upgraded=False) as (connection, migration):
        scenario = seed_scenario(connection)
        g2_commit(connection, scenario, payload=b"first", g2_only=True)
        connection.execute(migration.read_text(encoding="utf-8"))
        assert connection.execute("select institutional_snapshot,institutional_snapshot_sha256 "
            "from public.documentos_editor_revisoes where document_id=%s", (scenario["doc"],)).fetchone() == (None, None)
        second = commit(connection, scenario, expected=1, operation=uuid4(), payload=b"second")
        current_reference = snapshot(scenario, revision=3, header="Cadastro atual; contexto antigo desconhecido")
        restored = commit(connection, scenario, expected=2, operation=uuid4(), payload=b"first", restored=1,
                          institutional=current_reference)
        assert restored[1] == 3 and restored[9] == 1 and restored[11] == hashlib.sha256(current_reference).hexdigest()
        assert connection.execute("select institutional_snapshot from public.documentos_editor_revisoes "
            "where document_id=%s and revision=1", (scenario["doc"],)).fetchone() == (None,)
        # Restore a known context after the current reference has changed. The
        # historical source, not the current head's institutional data, travels.
        restored_known = commit(connection, scenario, expected=3, operation=uuid4(), payload=b"second", restored=2)
        assert restored_known[1] == 4 and restored_known[9] == 2 and restored_known[11] == second[11]
        assert restored_known[11] != restored[11]
