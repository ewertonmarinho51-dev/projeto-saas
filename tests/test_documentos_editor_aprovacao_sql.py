"""Real atomic individual approval; opaque fixtures make no native fidelity claim."""
from datetime import datetime, timezone
import hashlib
import json
import threading
import time
from uuid import uuid4

import pytest

from src.documentos_editor import _snapshot_bytes
from tests.test_documentos_editor_institucional_sql import database, commit
from tests.test_documentos_editor_sql import role, seed_scenario


@pytest.fixture(scope="module")
def approval_db():
    with database() as (connection, _):
        yield connection


@pytest.fixture
def scenario(approval_db):
    value = seed_scenario(approval_db)
    competence(approval_db, value, "revisor_juridico")
    commit(approval_db, value)
    return value


def competence(connection, scenario, name, *, app_role="usuario"):
    scenario["owner"]["app_metadata"].update(papel_governanca=name, papel=app_role)
    connection.execute("update public.usuarios set papel_governanca=%s,papel=%s where auth_user_id=%s",
        (name, app_role, scenario["owner"]["sub"]))


def inputs(connection, scenario):
    from psycopg.types.json import Jsonb
    with role(connection, "service_role") as cursor:
        cursor.execute("select public.documento_editor_fontes_aprovacao(%s,%s)", (scenario["doc"], Jsonb(scenario["owner"])))
        sources = cursor.fetchone()[0]
    row = connection.execute("select content_hash,institutional_snapshot,institutional_snapshot_sha256 "
        "from public.documentos_editor_revisoes where document_id=%s and revision=1", (scenario["doc"],)).fetchone()
    snapshot = dict(json.loads(bytes(row[1])), phase="approved", approved_revision=1,
        approved_content_hash=row[0], approved_engine_manifest_sha256="a" * 64, draft_reference_sha256=row[2])
    evidence = dict(schema="gc-wordcraft-approval/v1", document_id=str(scenario["doc"]), revision=1,
        content_hash=row[0], engine_manifest_sha256="a" * 64, coverage="complete_textual_projection",
        scope="individual_revision_review", official_emission=False,
        quality={"score": 85, "criticos": []}, gate={"bloqueia": False})
    evidence["evaluated_at"] = datetime.now(timezone.utc).isoformat()
    return dict(sources=sources, snapshot=_snapshot_bytes(snapshot), evidence=evidence, digest=row[0], operation=uuid4())


def approve(connection, scenario, params, *, claims=None, replay=False, db_role="service_role"):
    from psycopg.types.json import Jsonb
    snapshot = params["snapshot"] if not replay else None
    arguments = (scenario["doc"], params.get("revision", 1), params["digest"], params["operation"],
        Jsonb(claims or scenario["owner"]), Jsonb(params["sources"]) if not replay else None,
        snapshot, hashlib.sha256(snapshot).hexdigest() if snapshot else None,
        Jsonb(params["evidence"]) if not replay else None)
    with role(connection, db_role, claims):
        result = connection.execute("select * from public.documento_editor_aprovar(" + ",".join(["%s"] * 9) + ")", arguments).fetchone()
        assert connection.execute("select auth.jwt()->>'role'").fetchone() == (db_role,)
        return result


def counts(connection, scenario):
    return connection.execute("select d.status,(select count(*) from public.governanca_aprovacoes a "
        "where a.entidade_id=d.id),(select count(*) from public.governanca_eventos e join "
        "public.governanca_aprovacoes a on a.id=e.entidade_id where a.entidade_id=d.id) "
        "from public.documentos_editor d where d.id=%s", (scenario["doc"],)).fetchone()


def test_atomic_act_freezes_history_and_retry_without_reinterpreting_registry(approval_db, scenario):
    data = inputs(approval_db, scenario)
    first = approve(approval_db, scenario, data)
    assert first[1:5] == (scenario["doc"], 1, data["digest"], data["operation"])
    assert first[7] is False and counts(approval_db, scenario) == ("aprovado", 1, 1)
    approval_db.execute("update public.secretarias set cabecalho='LATER REGISTRY' where id=%s",
        (scenario["owner"]["app_metadata"]["secretaria_id"],))
    again = approve(approval_db, scenario, data, replay=True)
    assert again[:7] == first[:7] and again[7] is True
    assert approval_db.execute("select documentos,aprovados,etapa from public.processos where id=%s",
        (scenario["process"],)).fetchone() == ({"dfd": "legacy untouched"}, [], 0)
    stored = approval_db.execute("select native_snapshot,native_sources from public.governanca_aprovacoes where id=%s", (first[0],)).fetchone()
    assert bytes(stored[0]) == data["snapshot"] and stored[1] == data["sources"]
    with pytest.raises(Exception):
        commit(approval_db, scenario, expected=1, operation=uuid4())


@pytest.mark.parametrize("changed", ["revision", "sources", "quality", "snapshot", "build"])
def test_stale_or_misbound_act_rolls_back_everything(approval_db, scenario, changed):
    import psycopg
    data = inputs(approval_db, scenario)
    if changed == "revision": data["revision"] = 2
    if changed == "sources": data["sources"]["processo"]["dados"] = {"changed": True}
    if changed == "quality": data["evidence"]["gate"]["bloqueia"] = True
    if changed == "snapshot":
        value = json.loads(data["snapshot"]); value["identity"] = {"forged": True}; data["snapshot"] = _snapshot_bytes(value)
    if changed == "build": data["evidence"]["engine_manifest_sha256"] = "b" * 64
    with pytest.raises((psycopg.errors.SerializationFailure, psycopg.errors.InvalidParameterValue)):
        approve(approval_db, scenario, data)
    assert counts(approval_db, scenario) == ("rascunho", 0, 0)


@pytest.mark.parametrize("governance,allowed", [("revisor_juridico", True), ("admin_municipal", True),
    ("proprietario", True), ("admin_global", True), ("publicador", False), ("auditor", False), (None, False)])
def test_existing_competence_matrix_is_reused(approval_db, scenario, governance, allowed):
    import psycopg
    competence(approval_db, scenario, governance)
    if allowed:
        approve(approval_db, scenario, inputs(approval_db, scenario))
        assert counts(approval_db, scenario) == ("aprovado", 1, 1)
    else:
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            approve(approval_db, scenario, inputs(approval_db, scenario))
        assert counts(approval_db, scenario) == ("rascunho", 0, 0)


def test_admin_fallback_and_profile_revocation_are_current_backend_facts(approval_db, scenario):
    import psycopg
    data = inputs(approval_db, scenario)
    approval_db.execute("update public.usuarios set papel_governanca='auditor' where auth_user_id=%s", (scenario["owner"]["sub"],))
    with pytest.raises(psycopg.errors.InsufficientPrivilege): approve(approval_db, scenario, data)
    competence(approval_db, scenario, None, app_role="admin")
    approve(approval_db, scenario, inputs(approval_db, scenario))
    approval_db.execute("update public.usuarios set ativo=false where auth_user_id=%s", (scenario["owner"]["sub"],))
    with pytest.raises(psycopg.errors.InsufficientPrivilege): approve(approval_db, scenario, data, replay=True)


def test_native_approval_cannot_be_forged_or_changed_through_network_roles(approval_db, scenario):
    import psycopg
    data = inputs(approval_db, scenario)
    with pytest.raises(psycopg.errors.InsufficientPrivilege):
        approve(approval_db, scenario, data, db_role="authenticated", claims=scenario["owner"])
    with pytest.raises(psycopg.errors.InsufficientPrivilege):
        with role(approval_db, "authenticated", scenario["owner"]):
            approval_db.execute("insert into public.governanca_aprovacoes(tenant_id,entidade_tipo,entidade_id) "
                "values(%s,'documento_editor',%s)", (scenario["owner"]["app_metadata"]["tenant_id"], scenario["doc"]))
    result = approve(approval_db, scenario, data)
    with pytest.raises(psycopg.errors.InsufficientPrivilege):
        with role(approval_db, "service_role"):
            approval_db.execute("update public.governanca_aprovacoes set motivo='rewrite' where id=%s", (result[0],))
    with role(approval_db, "authenticated", scenario["other"]):
        assert approval_db.execute("select id from public.governanca_aprovacoes where id=%s", (result[0],)).fetchall() == []


def test_canonical_trail_failure_rolls_back_approval_and_head(approval_db, scenario):
    import psycopg
    data = inputs(approval_db, scenario)
    with approval_db.transaction():
        approval_db.execute("create function public.qa_reject_approval_event() returns trigger language plpgsql as $$ "
            "begin raise exception 'QA event unavailable' using errcode='40001'; end $$")
        approval_db.execute("create trigger qa_reject_approval_event before insert on public.governanca_eventos "
            "for each row execute function public.qa_reject_approval_event()")
        with pytest.raises(psycopg.errors.SerializationFailure): approve(approval_db, scenario, data)
        assert counts(approval_db, scenario) == ("rascunho", 0, 0)
        approval_db.execute("drop trigger qa_reject_approval_event on public.governanca_eventos")
        approval_db.execute("drop function public.qa_reject_approval_event()")


def test_live_source_update_after_read_is_a_conflict(approval_db, scenario):
    import psycopg
    data = inputs(approval_db, scenario)
    approval_db.execute("update public.secretarias set cabecalho='changed before commit' where id=%s",
        (scenario["owner"]["app_metadata"]["secretaria_id"],))
    with pytest.raises(psycopg.errors.SerializationFailure): approve(approval_db, scenario, data)
    assert counts(approval_db, scenario) == ("rascunho", 0, 0)


def second_connection(connection):
    import psycopg
    return psycopg.connect(connection.info.dsn, autocommit=True)


def wait_for_lock(observer, pid):
    deadline = time.monotonic() + 4
    while time.monotonic() < deadline:
        row = observer.execute("select wait_event_type from pg_stat_activity where pid=%s", (pid,)).fetchone()
        if row and row[0] == "Lock": return
        threading.Event().wait(0.01)
    pytest.fail("approval did not actually contend on the concurrent writer")


@pytest.mark.parametrize("target", ["source", "phantom", "role", "head"])
def test_concurrent_writer_is_rechecked_after_the_lock_wait(approval_db, scenario, target):
    from concurrent.futures import ThreadPoolExecutor
    import psycopg
    data = inputs(approval_db, scenario)
    with second_connection(approval_db) as writer, second_connection(approval_db) as reviewer:
        pid = reviewer.info.backend_pid
        with ThreadPoolExecutor(max_workers=1) as pool:
            with writer.transaction():
                if target == "source":
                    writer.execute("update public.secretarias set cabecalho='CONCURRENT CHANGE' where id=%s",
                        (scenario["owner"]["app_metadata"]["secretaria_id"],))
                elif target == "phantom":
                    writer.execute("insert into public.secretarias(tenant_id,nome,sigla) values(%s,'Concurrent new unit','NEW')",
                        (scenario["owner"]["app_metadata"]["tenant_id"],))
                elif target == "role":
                    writer.execute("update public.usuarios set papel_governanca='auditor' where auth_user_id=%s",
                        (scenario["owner"]["sub"],))
                else:
                    commit(writer, scenario, expected=1, operation=uuid4(), payload=b"concurrent second head")
                future = pool.submit(approve, reviewer, scenario, data)
                wait_for_lock(approval_db, pid)
            expected = psycopg.errors.InsufficientPrivilege if target == "role" else psycopg.errors.SerializationFailure
            with pytest.raises(expected): future.result(timeout=5)
    assert counts(approval_db, scenario) == ("rascunho", 0, 0)


def test_source_lock_timeout_is_bounded_and_leaves_no_orphan_act(approval_db, scenario):
    import psycopg
    data = inputs(approval_db, scenario)
    with second_connection(approval_db) as writer, second_connection(approval_db) as reviewer:
        with writer.transaction():
            writer.execute("update public.secretarias set cabecalho='LOCK HELD' where id=%s",
                (scenario["owner"]["app_metadata"]["secretaria_id"],))
            started = time.monotonic()
            with pytest.raises(psycopg.errors.LockNotAvailable): approve(reviewer, scenario, data)
            assert 1.5 <= time.monotonic() - started < 4
        assert counts(approval_db, scenario) == ("rascunho", 0, 0)
    config = approval_db.execute("select proconfig from pg_proc where proname='documento_editor_aprovar'").fetchone()[0]
    assert "lock_timeout=2s" in config and "statement_timeout=5s" in config


def test_native_approval_is_not_visible_across_secretaries_of_same_tenant(approval_db, scenario):
    import psycopg
    from psycopg.types.json import Jsonb
    result = approve(approval_db, scenario, inputs(approval_db, scenario))
    foreign = scenario["colleague"]
    secretary = approval_db.execute("insert into public.secretarias(tenant_id,nome,sigla) values(%s,'Outra','OUT') returning id",
        (foreign["app_metadata"]["tenant_id"],)).fetchone()[0]
    foreign["app_metadata"].update(secretaria_id=str(secretary), papel_governanca="revisor_juridico")
    approval_db.execute("update public.usuarios set secretaria_id=%s,papel_governanca='revisor_juridico' where auth_user_id=%s",
        (secretary, foreign["sub"]))
    with role(approval_db, "authenticated", foreign):
        assert approval_db.execute("select id from public.governanca_aprovacoes where id=%s", (result[0],)).fetchall() == []
    with pytest.raises(psycopg.errors.InsufficientPrivilege):
        approve(approval_db, scenario, inputs(approval_db, scenario), claims=foreign, replay=True)
    with pytest.raises(psycopg.errors.InsufficientPrivilege):
        with role(approval_db, "service_role"):
            approval_db.execute("select public.documento_editor_fontes_aprovacao(%s,%s)", (scenario["doc"], Jsonb(foreign)))


def test_concurrent_exact_retry_produces_one_act_and_one_event(approval_db, scenario):
    from concurrent.futures import ThreadPoolExecutor
    data = inputs(approval_db, scenario)
    barrier = threading.Barrier(2)

    def run():
        with second_connection(approval_db) as connection:
            barrier.wait(timeout=3)
            return approve(connection, scenario, data)
    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(run) for _ in range(2)]
        results = [f.result(timeout=5) for f in futures]
    assert results[0][:7] == results[1][:7] and {r[7] for r in results} == {False, True}
    assert counts(approval_db, scenario) == ("aprovado", 1, 1)


def test_retry_cannot_change_actor_or_evidence_and_fresh_operation_cannot_reapprove(approval_db, scenario):
    import psycopg
    data = inputs(approval_db, scenario)
    approve(approval_db, scenario, data)
    data["evidence"]["quality"]["score"] = 86
    with pytest.raises(psycopg.errors.SerializationFailure): approve(approval_db, scenario, data)
    colleague = scenario["colleague"]
    colleague["app_metadata"]["papel_governanca"] = "revisor_juridico"
    approval_db.execute("update public.usuarios set papel_governanca='revisor_juridico' where auth_user_id=%s", (colleague["sub"],))
    with pytest.raises(psycopg.errors.SerializationFailure): approve(approval_db, scenario, data, claims=colleague, replay=True)
    data["operation"] = uuid4()
    with pytest.raises(psycopg.errors.InsufficientPrivilege): approve(approval_db, scenario, data, replay=True)
    assert counts(approval_db, scenario) == ("aprovado", 1, 1)


def test_statement_cancellation_during_trail_leaves_no_orphan_act(approval_db, scenario):
    import psycopg
    data = inputs(approval_db, scenario)
    try:
        approval_db.execute("create function public.qa_slow_approval_event() returns trigger language plpgsql as $$ "
            "begin perform pg_sleep(0.3); return new; end $$")
        approval_db.execute("create trigger qa_slow_approval_event before insert on public.governanca_eventos "
            "for each row execute function public.qa_slow_approval_event()")
        with second_connection(approval_db) as reviewer:
            reviewer.execute("set statement_timeout='100ms'")
            with pytest.raises(psycopg.errors.QueryCanceled): approve(reviewer, scenario, data)
        assert counts(approval_db, scenario) == ("rascunho", 0, 0)
    finally:
        approval_db.execute("drop trigger if exists qa_slow_approval_event on public.governanca_eventos")
        approval_db.execute("drop function if exists public.qa_slow_approval_event()")


def test_unqualified_actor_is_rejected_before_any_source_lock(approval_db, scenario):
    import psycopg
    data = inputs(approval_db, scenario)
    competence(approval_db, scenario, "publicador")
    with second_connection(approval_db) as writer, second_connection(approval_db) as reviewer:
        with writer.transaction():
            writer.execute("update public.secretarias set cabecalho='held by writer' where id=%s",
                (scenario["owner"]["app_metadata"]["secretaria_id"],))
            started = time.monotonic()
            with pytest.raises(psycopg.errors.InsufficientPrivilege): approve(reviewer, scenario, data)
            assert time.monotonic()-started < 1
    assert counts(approval_db, scenario) == ("rascunho", 0, 0)


def test_upgrade_preserves_legacy_and_unknown_approval_rows_without_inventing_binding(monkeypatch):
    from pathlib import Path
    import sys
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
    import ensaio_local as harness
    migration = "20261015174145_documentos_editor_aprovacao_nativa.sql"
    monkeypatch.setattr(harness, "SEQUENCIA_EM_ENSAIO", tuple(n for n in harness.SEQUENCIA_EM_ENSAIO if n != migration))
    with database() as (connection, _):
        scenario = seed_scenario(connection)
        for kind in ("artefato", "documento_editor"):
            connection.execute("insert into public.governanca_aprovacoes(tenant_id,entidade_tipo,entidade_id,decisao) "
                "values(%s,%s,%s,'APROVADO')", (scenario["owner"]["app_metadata"]["tenant_id"], kind, scenario["doc"]))
        connection.execute((harness.MIGRACOES / migration).read_text(encoding="utf-8"))
        rows = connection.execute("select decisao,native_revision,native_content_hash,native_snapshot "
            "from public.governanca_aprovacoes where entidade_id=%s order by entidade_tipo", (scenario["doc"],)).fetchall()
        assert rows == [("APROVADO", None, None, None), ("APROVADO", None, None, None)]
