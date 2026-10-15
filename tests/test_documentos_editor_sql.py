"""Real SQL contract proofs; opaque test bytes here do not prove native validity."""
from contextlib import contextmanager
import hashlib
import json
from uuid import uuid4

import pytest


@contextmanager
def role(connection, name, claims=None):
    assert name in {"authenticated", "anon", "service_role"}
    with connection.transaction():
        with connection.cursor() as cursor:
            cursor.execute("set local role " + name)
            cursor.execute("select set_config('request.jwt.claims', %s, true)",
                           (json.dumps(claims or {"role": name}),))
            yield cursor


@pytest.fixture
def scenario(banco):
    from psycopg.types.json import Jsonb
    result = {"doc": uuid4(), "operation": uuid4()}
    with banco.cursor() as cursor:
        for suffix in ("a", "b"):
            cursor.execute("insert into public.tenants (slug,nome,uf) values (%s,'QA','PA') returning id",
                           ("wordcraft-" + uuid4().hex,))
            tenant = cursor.fetchone()[0]
            cursor.execute("insert into public.secretarias (tenant_id,nome,sigla) values (%s,'QA','QA') returning id", (tenant,))
            secretary = cursor.fetchone()[0]
            for who in (("owner", "colleague") if suffix == "a" else ("other",)):
                meta = {"tenant_id": str(tenant), "secretaria_id": str(secretary), "papel": "usuario"}
                cursor.execute("insert into auth.users (email,raw_app_meta_data) values (%s,%s) returning id",
                               (uuid4().hex + "@example.invalid", Jsonb(meta)))
                uid = cursor.fetchone()[0]
                cursor.execute("insert into public.usuarios (nome,login,senha_hash,papel,tenant_id,secretaria_id,auth_user_id) "
                               "values ('QA',%s,'unused','usuario',%s,%s,%s)", (uuid4().hex, tenant, secretary, uid))
                result[who] = {"sub": str(uid), "role": "authenticated", "app_metadata": meta}
            if suffix == "a":
                cursor.execute("insert into public.processos (tenant_id,secretaria_id,auth_user_id,documentos) "
                               "values (%s,%s,%s,%s) returning id",
                               (tenant, secretary, result["owner"]["sub"], Jsonb({"dfd": "legacy untouched"})))
                result["process"] = cursor.fetchone()[0]
    return result


def commit(banco, scenario, *, expected=0, payload=b"opaque SQL fixture", operation=None, claims=None):
    from psycopg.types.json import Jsonb
    with role(banco, "service_role") as cursor:
        cursor.execute("select * from public.documento_editor_checkpoint(%s,%s,'dfd',%s,%s,%s,%s,%s)",
                       (scenario["doc"], scenario["process"], expected, operation or scenario["operation"],
                        payload, hashlib.sha256(payload).hexdigest(), Jsonb(claims or scenario["owner"])))
        result = cursor.fetchone()
        cursor.execute("select auth.jwt()->>'role'")
        assert cursor.fetchone()[0] == "service_role", "actor claims must not leak to the next request"
        return result


def test_commit_retry_and_immutable_revision(banco, scenario):
    first = commit(banco, scenario)
    retry = commit(banco, scenario)
    assert first[1] == retry[1] == 1
    assert first[-1] is False and retry[-1] is True
    with banco.cursor() as cursor:
        cursor.execute("select payload from public.documentos_editor_revisoes where document_id=%s", (scenario["doc"],))
        rows = cursor.fetchall()
        assert len(rows) == 1 and bytes(rows[0][0]) == b"opaque SQL fixture"
        cursor.execute("select documentos from public.processos where id=%s", (scenario["process"],))
        assert cursor.fetchone()[0] == {"dfd": "legacy untouched"}


def test_stale_and_reused_operation_are_atomic(banco, scenario):
    import psycopg
    commit(banco, scenario)
    for operation in (scenario["operation"], uuid4()):
        with pytest.raises(psycopg.errors.SerializationFailure):
            commit(banco, scenario, operation=operation, payload=b"changed")
    assert commit(banco, scenario, expected=1, operation=uuid4(), payload=b"revision two")[1] == 2
    with banco.cursor() as cursor:
        cursor.execute("select payload from public.documentos_editor_revisoes where document_id=%s order by revision", (scenario["doc"],))
        assert [bytes(r[0]) for r in cursor.fetchall()] == [b"opaque SQL fixture", b"revision two"]


def test_two_connections_cannot_both_commit_the_same_base_revision(banco, scenario):
    import os
    import threading
    from concurrent.futures import ThreadPoolExecutor
    import psycopg
    commit(banco, scenario)
    dsn = psycopg.conninfo.make_conninfo(os.environ["GOVDOCS_ENSAIO_PG_DSN"],
                                       dbname=banco.info.dbname, connect_timeout=5)
    barrier = threading.Barrier(2)

    def attempt(index):
        with psycopg.connect(dsn, autocommit=True) as connection:
            barrier.wait(timeout=5)
            try:
                commit(connection, scenario, expected=1, operation=uuid4(), payload=f"writer-{index}".encode())
                return "committed"
            except psycopg.errors.SerializationFailure:
                return "conflict"

    with ThreadPoolExecutor(max_workers=2) as pool:
        assert sorted(pool.map(attempt, (1, 2))) == ["committed", "conflict"]
    with banco.cursor() as cursor:
        cursor.execute("select count(*),max(revision) from public.documentos_editor_revisoes where document_id=%s", (scenario["doc"],))
        assert cursor.fetchone() == (2, 2)


@pytest.mark.parametrize("who,expected", [("owner", 1), ("colleague", 1), ("other", 0)])
def test_rls_uses_existing_process_scope(banco, scenario, who, expected):
    commit(banco, scenario)
    with role(banco, "authenticated", scenario[who]) as cursor:
        cursor.execute("select count(*) from public.documentos_editor_revisoes where document_id=%s", (scenario["doc"],))
        assert cursor.fetchone()[0] == expected


@pytest.mark.parametrize("who", ["colleague", "other"])
def test_server_commit_cannot_impersonate_a_reader_as_owner(banco, scenario, who):
    import psycopg
    with pytest.raises(psycopg.errors.InsufficientPrivilege):
        commit(banco, scenario, claims=scenario[who])
    with banco.cursor() as cursor:
        cursor.execute("select count(*) from public.documentos_editor where id=%s", (scenario["doc"],))
        assert cursor.fetchone()[0] == 0


def test_history_is_not_mutable_even_with_server_role(banco, scenario):
    import psycopg
    commit(banco, scenario)
    for statement in ("update public.documentos_editor_revisoes set payload='changed'::bytea",
                      "delete from public.documentos_editor_revisoes", "truncate public.documentos_editor_revisoes"):
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            with role(banco, "service_role") as cursor:
                cursor.execute(statement)


def test_public_roles_cannot_bypass_the_native_validation_owner(banco, scenario):
    import psycopg
    for name in ("anon", "authenticated"):
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            with role(banco, name, scenario["owner"] if name == "authenticated" else None) as cursor:
                cursor.execute("select * from public.documento_editor_checkpoint(null,null,null,null,null,null,null,null)")


def test_revoked_profile_loses_read_and_commit_with_old_claims(banco, scenario):
    import psycopg
    commit(banco, scenario)
    with banco.cursor() as cursor:
        cursor.execute("update public.usuarios set ativo=false where auth_user_id=%s", (scenario["owner"]["sub"],))
    with role(banco, "authenticated", scenario["owner"]) as cursor:
        cursor.execute("select count(*) from public.documentos_editor_revisoes where document_id=%s", (scenario["doc"],))
        assert cursor.fetchone()[0] == 0
    with pytest.raises(psycopg.errors.InsufficientPrivilege):
        commit(banco, scenario, expected=1, operation=uuid4())


def test_approved_legacy_document_cannot_be_autosaved(banco, scenario):
    import psycopg
    commit(banco, scenario)
    with banco.cursor() as cursor:
        cursor.execute("update public.processos set aprovados=array['dfd'] where id=%s", (scenario["process"],))
    with pytest.raises(psycopg.errors.InsufficientPrivilege):
        commit(banco, scenario, expected=1, operation=uuid4())


def test_context_is_verified_and_excludes_user_metadata(banco, scenario):
    claims = {**scenario["owner"], "user_metadata": {"papel": "admin"}}
    with role(banco, "authenticated", claims) as cursor:
        cursor.execute("select public.documento_editor_contexto()")
        assert cursor.fetchone()[0] == scenario["owner"]
