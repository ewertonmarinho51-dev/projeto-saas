"""Real transaction/RLS proofs for the native official-emission boundary."""
import hashlib
from uuid import uuid4

import pytest

from tests.test_documentos_editor_institucional_sql import database, commit
from tests.test_documentos_editor_sql import role, seed_scenario


@pytest.fixture(scope="module")
def emission_db():
    with database() as (connection, _):
        yield connection


@pytest.fixture
def emission(emission_db):
    from psycopg.types.json import Jsonb
    scenario = seed_scenario(emission_db)
    scenario["owner"]["app_metadata"].update(
        papel="admin", papel_governanca="admin_municipal")
    emission_db.execute("update public.usuarios set papel='admin',"
        "papel_governanca='admin_municipal' where auth_user_id=%s",
        (scenario["owner"]["sub"],))
    commit(emission_db, scenario)
    revision, source_hash = emission_db.execute(
        "select revision,content_hash from public.documentos_editor where id=%s",
        (scenario["doc"],)).fetchone()
    approval_id, snapshot = uuid4(), b"synthetic immutable approval snapshot"
    snapshot_hash = hashlib.sha256(snapshot).hexdigest()
    emission_db.execute("insert into public.governanca_aprovacoes(id,tenant_id,entidade_tipo,"
        "entidade_id,papel_exigido,aprovador,decisao,native_revision,native_content_hash,"
        "native_operation_id,native_snapshot,native_snapshot_sha256,native_evidence,native_sources) "
        "values(%s,%s,'documento_editor',%s,'admin_municipal',%s,'APROVADO',%s,%s,%s,%s,%s,%s,%s)",
        (approval_id, scenario["owner"]["app_metadata"]["tenant_id"], scenario["doc"],
         scenario["owner"]["sub"], revision, source_hash, uuid4(), snapshot,
         snapshot_hash, Jsonb({}), Jsonb({})))
    emission_db.execute("update public.documentos_editor set status='aprovado' where id=%s",
                        (scenario["doc"],))
    documents = [{"tipo": "dfd", "document_id": str(scenario["doc"]),
        "revision": revision, "source_sha256": source_hash,
        "approval_id": str(approval_id), "approval_snapshot_sha256": snapshot_hash,
        "engine_manifest_sha256": "a" * 64,
        "docx_sha256": hashlib.sha256(b"individual docx").hexdigest(),
        "pdf_sha256": hashlib.sha256(b"individual pdf").hexdigest()}]
    packages = {"docx": b"exact native DOCX package", "pdf": b"exact native PDF package"}
    package_meta = {fmt: {"sha256": hashlib.sha256(payload).hexdigest(),
                          "bytes": len(payload)} for fmt, payload in packages.items()}
    manifest = {"schema": "gc-wordcraft-official-emission/v1",
        "official_emission": True, "processo_id": str(scenario["process"]),
        "engine_manifest_sha256": "a" * 64, "documents": documents,
        "packages": package_meta}
    return scenario, documents, packages, manifest, uuid4()


def emit(connection, fixture, *, documents=None, packages=None, manifest=None,
         operation=None, claims=None, db_role="service_role"):
    from psycopg.types.json import Jsonb
    scenario, original_documents, original_packages, original_manifest, original_operation = fixture
    documents = original_documents if documents is None else documents
    packages = original_packages if packages is None else packages
    manifest = original_manifest if manifest is None else manifest
    operation = original_operation if operation is None else operation
    with role(connection, db_role, claims or scenario["owner"]):
        return connection.execute("select * from public.documento_editor_emitir("
            + ",".join(["%s"] * 10) + ")", (scenario["process"], operation, "a" * 64,
            Jsonb(documents), Jsonb(manifest), packages["docx"],
            hashlib.sha256(packages["docx"]).hexdigest(), packages["pdf"],
            hashlib.sha256(packages["pdf"]).hexdigest(),
            Jsonb(claims or scenario["owner"]))).fetchone()


def test_emission_is_atomic_immutable_and_exact_retry_is_idempotent(emission_db, emission):
    import psycopg
    first = emit(emission_db, emission)
    again = emit(emission_db, emission)
    assert first[:6] == again[:6] and first[6] is False and again[6] is True
    scenario, documents, packages, _, _ = emission
    row = emission_db.execute("select docx_package,pdf_package,documentos from "
        "public.documentos_editor_emissoes where id=%s", (first[0],)).fetchone()
    assert bytes(row[0]) == packages["docx"] and bytes(row[1]) == packages["pdf"]
    assert row[2] == documents
    assert emission_db.execute("select status from public.documentos_editor where id=%s",
        (scenario["doc"],)).fetchone() == ("emitido",)
    assert emission_db.execute("select count(*) from public.governanca_eventos where "
        "tipo_evento='publicacao_registrada' and entidade_id=%s", (first[0],)).fetchone() == (1,)
    with pytest.raises(psycopg.errors.InsufficientPrivilege):
        with role(emission_db, "service_role"):
            emission_db.execute("update public.documentos_editor_emissoes set manifest='{}'")


def test_changed_source_or_package_never_creates_partial_emission(emission_db, emission):
    import copy
    import psycopg
    scenario, documents, packages, manifest, _ = emission
    bad_documents = copy.deepcopy(documents)
    bad_documents[0]["source_sha256"] = "f" * 64
    bad_manifest = copy.deepcopy(manifest); bad_manifest["documents"] = bad_documents
    with pytest.raises(psycopg.ProgrammingError) as captured:
        emit(emission_db, emission, documents=bad_documents, manifest=bad_manifest,
             operation=uuid4())
    assert captured.value.sqlstate == "PT409"
    assert emission_db.execute("select count(*) from public.documentos_editor_emissoes where "
        "processo_id=%s", (scenario["process"],)).fetchone() == (0,)
    altered = {**packages, "pdf": packages["pdf"] + b" changed"}
    with pytest.raises(psycopg.errors.InvalidParameterValue):
        emit(emission_db, emission, packages=altered, operation=uuid4())
    assert emission_db.execute("select status from public.documentos_editor where id=%s",
        (scenario["doc"],)).fetchone() == ("aprovado",)


def test_authenticated_cannot_call_or_forge_emission_and_other_tenant_cannot_read(emission_db, emission):
    import psycopg
    scenario = emission[0]
    with pytest.raises(psycopg.errors.InsufficientPrivilege):
        emit(emission_db, emission, db_role="authenticated")
    receipt = emit(emission_db, emission)
    with pytest.raises(psycopg.errors.InsufficientPrivilege):
        with role(emission_db, "authenticated", scenario["owner"]):
            emission_db.execute("insert into public.documentos_editor_emissoes(id) values(%s)",
                                (uuid4(),))
    with role(emission_db, "authenticated", scenario["other"]):
        assert emission_db.execute("select id from public.documentos_editor_emissoes where id=%s",
                                   (receipt[0],)).fetchall() == []


def test_sql_refuses_srp_emission_without_arp(emission_db, emission):
    import psycopg
    scenario = emission[0]
    emission_db.execute("update public.processos set dados=jsonb_build_object("
        "'modelo_execucao','Sistema de Registro de Preços (SRP)') where id=%s",
        (scenario["process"],))
    with pytest.raises(psycopg.ProgrammingError) as captured:
        emit(emission_db, emission)
    assert captured.value.sqlstate == "PT409"
    assert emission_db.execute("select count(*) from public.documentos_editor_emissoes "
        "where processo_id=%s", (scenario["process"],)).fetchone() == (0,)


def test_sql_refuses_residual_arp_in_non_srp_process(emission_db, emission):
    import copy
    import psycopg
    scenario, documents, packages, manifest, _ = emission
    emission_db.execute("update public.processos set dados=jsonb_build_object("
        "'modelo_execucao','Entrega integral') where id=%s", (scenario["process"],))
    emission_db.execute("update public.documentos_editor set tipo='arp' where id=%s",
                        (scenario["doc"],))
    altered_documents = copy.deepcopy(documents)
    altered_documents[0]["tipo"] = "arp"
    altered_manifest = copy.deepcopy(manifest)
    altered_manifest["documents"] = altered_documents
    with pytest.raises(psycopg.ProgrammingError) as captured:
        emit(emission_db, emission, documents=altered_documents,
             manifest=altered_manifest)
    assert captured.value.sqlstate == "PT409"
    assert emission_db.execute("select count(*) from public.documentos_editor_emissoes "
        "where processo_id=%s", (scenario["process"],)).fetchone() == (0,)
