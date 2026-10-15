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
    return seed_scenario(banco)


def seed_scenario(banco):
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


def commit(banco, scenario, *, expected=0, payload=b"opaque SQL fixture", operation=None, claims=None,
           build="a" * 64, legacy=False, provenance_only=False, original=None, restored=None,
           index=None, mode=None):
    from psycopg.types.json import Jsonb
    if not legacy and not provenance_only:
        if mode is None:
            mode = "initial"
            if expected:
                with banco.cursor() as lookup:
                    lookup.execute("select block_index,engine_build_sha256 from public.documentos_editor_revisoes "
                                   "where document_id=%s and revision=%s", (scenario["doc"], expected))
                    base = lookup.fetchone()
                    mode = "rebuilt_missing_index" if not base or base[0] is None else "reconciled" if base[1] == build else "rebuilt_build"
        if index is None:
            # SQL fixture only. Native projection is covered by separate tests.
            index = json.dumps({"schema": "gc-wordcraft-block-index/v1", "document_id": str(scenario["doc"]),
                "revision": expected + 1, "content_hash": hashlib.sha256(payload).hexdigest(),
                "engine_manifest_sha256": build, "blocos": [], "invalidacoes": [], "areas_nao_enderecaveis": []},
                sort_keys=True, separators=(",", ":")).encode()
    with role(banco, "service_role") as cursor:
        params = (scenario["doc"], scenario["process"], "dfd", expected, operation or scenario["operation"],
                  payload, hashlib.sha256(payload).hexdigest(), Jsonb(claims or scenario["owner"]))
        if not legacy:
            params += (build,)
        if not legacy and not provenance_only:
            params += (index, hashlib.sha256(index).hexdigest(), mode,
                       original[0] if original else None, original[1] if original else None,
                       Jsonb(original[2]) if original else None, restored)
        cursor.execute("select * from public.documento_editor_checkpoint(" + ",".join(["%s"] * len(params)) + ")", params)
        result = cursor.fetchone()
        cursor.execute("select auth.jwt()->>'role'")
        assert cursor.fetchone()[0] == "service_role", "actor claims must not leak to the next request"
        return result


def test_commit_retry_and_immutable_revision(banco, scenario):
    first = commit(banco, scenario)
    retry = commit(banco, scenario)
    assert first[1] == retry[1] == 1
    assert first[4] is False and retry[4] is True
    assert first[5:7] == retry[5:7] == ("a" * 64, "server_manifest_sha256")
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
                cursor.execute("select * from public.documento_editor_checkpoint(" + ",".join(["null"] * 16) + ")")


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


def test_same_operation_cannot_rewrite_its_original_validation_build(banco, scenario):
    import psycopg
    original = commit(banco, scenario, build="a" * 64)
    with pytest.raises(psycopg.errors.SerializationFailure):
        commit(banco, scenario, build="b" * 64)
    assert commit(banco, scenario, build="a" * 64)[5:] == original[5:]
    next_receipt = commit(banco, scenario, expected=1, operation=uuid4(), build="b" * 64)
    assert next_receipt[1] == 2 and next_receipt[5] == "b" * 64
    with banco.cursor() as cursor:
        cursor.execute("select revision,engine_build_sha256 from public.documentos_editor_revisoes "
                       "where document_id=%s order by revision", (scenario["doc"],))
        assert cursor.fetchall() == [(1, "a" * 64), (2, "b" * 64)]


@pytest.mark.parametrize("build", [None, "", "a" * 63, "A" * 64, "../invalid"])
def test_new_commit_requires_valid_build_before_any_write(banco, scenario, build):
    import psycopg
    with pytest.raises(psycopg.errors.InvalidParameterValue):
        commit(banco, scenario, build=build)
    with banco.cursor() as cursor:
        cursor.execute("select count(*) from public.documentos_editor where id=%s", (scenario["doc"],))
        assert cursor.fetchone()[0] == 0


def test_only_new_private_signature_exists_and_cannot_omit_build(banco):
    with banco.cursor() as cursor:
        cursor.execute("select pronargs,prosecdef,proconfig,"
                       "has_function_privilege('anon',oid,'execute'),"
                       "has_function_privilege('authenticated',oid,'execute'),"
                       "has_function_privilege('service_role',oid,'execute') "
                       "from pg_proc where pronamespace='public'::regnamespace "
                       "and proname='documento_editor_checkpoint'")
        assert cursor.fetchall() == [(16, False, ['search_path=""'], False, False, True)]


def test_even_direct_server_insert_cannot_create_an_unrecorded_new_revision(banco, scenario):
    import psycopg
    commit(banco, scenario)
    with pytest.raises(psycopg.errors.CheckViolation):
        with role(banco, "service_role") as cursor:
            cursor.execute("insert into public.documentos_editor_revisoes "
                           "(document_id,revision,source_revision,operation_id,payload,content_hash,created_by) "
                           "select document_id,2,1,%s,payload,content_hash,created_by "
                           "from public.documentos_editor_revisoes where document_id=%s", (uuid4(), scenario["doc"]))
    with banco.cursor() as cursor:
        cursor.execute("select count(*) from public.documentos_editor_revisoes where document_id=%s", (scenario["doc"],))
        assert cursor.fetchone()[0] == 1


def test_migration_preserves_legacy_revision_without_retroattributing_a_build(ensaio_sql, monkeypatch):
    """Apply exact migration after committing through the former schema/API."""
    import os
    import sys
    from pathlib import Path
    import psycopg

    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
    import ensaio_local as harness
    migration = "20261015045831_documentos_editor_proveniencia.sql"
    dsn_base = os.environ["GOVDOCS_ENSAIO_PG_DSN"]
    harness.exigir_dsn_local(dsn_base)
    dsn, name = harness.criar_banco_descartavel(dsn_base)
    try:
        with psycopg.connect(dsn, autocommit=True) as connection:
            with monkeypatch.context() as legacy_schema:
                legacy_schema.setattr(harness, "SEQUENCIA_EM_ENSAIO",
                    tuple(item for item in harness.SEQUENCIA_EM_ENSAIO if item not in {
                        migration, "20261015122441_documentos_editor_persistencia_g2.sql"}))
                harness.preparar(connection)
            old = seed_scenario(connection)
            before = commit(connection, old, legacy=True)
            with connection.cursor() as cursor:
                cursor.execute((harness.MIGRACOES / migration).read_text(encoding="utf-8"))
                cursor.execute("select revision,payload,content_hash,operation_id,engine_build_sha256,validation_provenance "
                               "from public.documentos_editor_revisoes where document_id=%s", (old["doc"],))
                row = cursor.fetchone()
                assert (row[0], bytes(row[1]), row[2], row[3]) == (before[1], b"opaque SQL fixture", before[2], old["operation"])
                assert row[4:] == (None, "legacy_unrecorded")
            # Retrying an operation whose original build is unknown cannot invent
            # provenance. A distinct next revision can record today's validator.
            with pytest.raises(psycopg.errors.SerializationFailure):
                commit(connection, old, provenance_only=True)
            assert commit(connection, old, expected=1, operation=uuid4(), provenance_only=True)[5:] == ("a" * 64, "server_manifest_sha256")
            with connection.cursor() as cursor:
                cursor.execute("select engine_build_sha256,validation_provenance "
                               "from public.documentos_editor_revisoes where document_id=%s and revision=1", (old["doc"],))
                assert cursor.fetchone() == (None, "legacy_unrecorded")
                cursor.execute((harness.MIGRACOES / "20261015122441_documentos_editor_persistencia_g2.sql").read_text(encoding="utf-8"))
                cursor.execute("select block_index,block_index_sha256,index_mode from public.documentos_editor_revisoes "
                               "where document_id=%s order by revision", (old["doc"],))
                assert cursor.fetchall() == [(None, None, None), (None, None, None)]
            assert commit(connection, old, expected=2, operation=uuid4())[8] == "rebuilt_missing_index"
    finally:
        harness.descartar_banco(dsn_base, name)


def original_source(payload=b"# Original\r\nsem alteracao", fmt="markdown"):
    return (fmt, payload, {"schema": "gc-wordcraft-import/v1", "source_format": fmt,
        "source_sha256": hashlib.sha256(payload).hexdigest(), "fidelity": "pending_manual_review",
        "pipeline": "govconnect_docx_wordcraft" if fmt == "markdown" else "wordcraft_docx"})


def test_original_and_index_are_private_immutable_and_correlated_on_retry(banco, scenario):
    import psycopg
    original = original_source()
    receipt = commit(banco, scenario, original=original)
    assert receipt[10] == hashlib.sha256(original[1]).hexdigest()
    assert commit(banco, scenario, original=original)[4] is True
    with role(banco, "authenticated", scenario["owner"]) as cursor:
        cursor.execute("select original_payload,original_hash,block_index,block_index_sha256 from public.documentos_editor_revisoes "
                       "where document_id=%s", (scenario["doc"],))
        row = cursor.fetchone()
        assert bytes(row[0]) == original[1] and row[1] == receipt[10]
        assert hashlib.sha256(bytes(row[2])).hexdigest() == row[3] == receipt[7]
    with role(banco, "authenticated", scenario["other"]) as cursor:
        cursor.execute("select original_payload,block_index from public.documentos_editor_revisoes where document_id=%s", (scenario["doc"],))
        assert cursor.fetchall() == []
    for actor in ("authenticated", "service_role"):
        for column in ("original_payload", "block_index", "conversion_report"):
            value = "'{}'::jsonb" if column == "conversion_report" else "'changed'::bytea"
            with pytest.raises(psycopg.errors.InsufficientPrivilege):
                with role(banco, actor, scenario["owner"] if actor == "authenticated" else None) as cursor:
                    cursor.execute(f"update public.documentos_editor_revisoes set {column}={value}")


def test_retry_cannot_change_original_report_index_or_restoration_metadata(banco, scenario):
    import psycopg
    source = original_source()
    commit(banco, scenario, original=source)
    alternate_report = {**source[2], "pipeline": "changed"}
    with pytest.raises(psycopg.errors.SerializationFailure):
        commit(banco, scenario, original=(source[0], source[1], alternate_report))
    with pytest.raises(psycopg.errors.SerializationFailure):
        commit(banco, scenario, original=original_source(b"different original"))
    with banco.cursor() as cursor:
        cursor.execute("select block_index from public.documentos_editor_revisoes where document_id=%s", (scenario["doc"],))
        altered = json.loads(bytes(cursor.fetchone()[0]))
        altered["areas_nao_enderecaveis"] = ["different"]
    with pytest.raises(psycopg.errors.SerializationFailure):
        commit(banco, scenario, original=source, index=json.dumps(altered).encode())
    assert commit(banco, scenario, original=source)[4] is True


def test_stale_import_rolls_back_original_and_sidecar_together(banco, scenario):
    import psycopg
    commit(banco, scenario)
    with pytest.raises(psycopg.errors.SerializationFailure):
        commit(banco, scenario, operation=uuid4(), original=original_source())
    with banco.cursor() as cursor:
        cursor.execute("select count(*),count(original_payload),max(revision) from public.documentos_editor_revisoes "
                       "where document_id=%s", (scenario["doc"],))
        assert cursor.fetchone() == (1, 0, 1)


def test_restore_creates_a_new_revision_without_rewinding_or_mutating_source(banco, scenario):
    import psycopg
    commit(banco, scenario, payload=b"first")
    commit(banco, scenario, expected=1, operation=uuid4(), payload=b"second")
    operation = uuid4()
    receipt = commit(banco, scenario, expected=2, operation=operation, payload=b"first", restored=1)
    assert receipt[1] == 3 and receipt[9] == 1
    assert commit(banco, scenario, expected=2, operation=operation, payload=b"first", restored=1)[4] is True
    with pytest.raises(psycopg.errors.SerializationFailure):
        commit(banco, scenario, expected=2, operation=uuid4(), payload=b"first", restored=1)
    with banco.cursor() as cursor:
        cursor.execute("select revision,payload,restored_from_revision from public.documentos_editor_revisoes "
                       "where document_id=%s order by revision", (scenario["doc"],))
        assert [(r[0], bytes(r[1]), r[2]) for r in cursor.fetchall()] == [(1, b"first", None), (2, b"second", None), (3, b"first", 1)]
        cursor.execute("select revision from public.documentos_editor where id=%s", (scenario["doc"],))
        assert cursor.fetchone() == (3,)


def test_restore_cannot_forge_source_reference_or_modify_an_approved_head(banco, scenario):
    import psycopg
    commit(banco, scenario, payload=b"first")
    for restored, payload in ((1, b"different"), (2, b"first")):
        with pytest.raises(psycopg.errors.InvalidParameterValue):
            commit(banco, scenario, expected=1, operation=uuid4(), payload=payload, restored=restored)
    with banco.cursor() as cursor:
        cursor.execute("update public.documentos_editor set status='aprovado' where id=%s", (scenario["doc"],))
    with pytest.raises(psycopg.errors.InsufficientPrivilege):
        commit(banco, scenario, expected=1, operation=uuid4(), payload=b"first", restored=1)


def test_retry_cannot_change_restore_reference_even_when_source_bytes_match(banco, scenario):
    import psycopg
    commit(banco, scenario, payload=b"same")
    commit(banco, scenario, expected=1, operation=uuid4(), payload=b"same")
    operation = uuid4()
    commit(banco, scenario, expected=2, operation=operation, payload=b"same", restored=1)
    with pytest.raises(psycopg.errors.SerializationFailure):
        commit(banco, scenario, expected=2, operation=operation, payload=b"same", restored=2)


def test_authenticated_user_cannot_insert_a_forged_sidecar_or_original_directly(banco, scenario):
    import psycopg
    commit(banco, scenario, original=original_source())
    with pytest.raises(psycopg.errors.InsufficientPrivilege):
        with role(banco, "authenticated", scenario["owner"]) as cursor:
            columns = ("document_id,revision,source_revision,operation_id,payload,content_hash,created_by,"
                       "engine_build_sha256,block_index,block_index_sha256,index_mode,"
                       "original_format,original_payload,original_hash,conversion_report")
            cursor.execute("insert into public.documentos_editor_revisoes (" + columns + ") select " + columns
                           + " from public.documentos_editor_revisoes")


@pytest.mark.parametrize("change", ["source_hash", "fidelity", "format", "index_document", "index_revision"])
def test_incoherent_source_or_index_is_rejected_before_persistence(banco, scenario, change):
    import psycopg
    source = original_source()
    index = None
    if change == "source_hash":
        source[2]["source_sha256"] = "b" * 64
    elif change == "fidelity":
        source[2]["fidelity"] = "approved"
    elif change == "format":
        source = ("pdf", source[1], source[2])
    else:
        index = json.dumps({"schema": "gc-wordcraft-block-index/v1", "document_id": str(uuid4()) if change == "index_document" else str(scenario["doc"]),
            "revision": 99 if change == "index_revision" else 1, "content_hash": hashlib.sha256(b"opaque SQL fixture").hexdigest(),
            "engine_manifest_sha256": "a" * 64, "blocos": [], "invalidacoes": [], "areas_nao_enderecaveis": []}).encode()
    with pytest.raises(psycopg.errors.InvalidParameterValue):
        commit(banco, scenario, original=source, index=index)
    with banco.cursor() as cursor:
        cursor.execute("select count(*) from public.documentos_editor where id=%s", (scenario["doc"],))
        assert cursor.fetchone() == (0,)
