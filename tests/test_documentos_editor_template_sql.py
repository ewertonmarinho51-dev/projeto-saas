"""Real PostgreSQL proofs for atomic governed-template application."""
import hashlib
import json
from uuid import uuid4

import pytest

from tests.test_documentos_editor_institucional_sql import database, commit
from tests.test_documentos_editor_sql import role, seed_scenario


@pytest.fixture(scope="module")
def template_db():
    with database() as (connection, _):
        yield connection


def fixture(connection):
    from psycopg.types.json import Jsonb
    scenario = seed_scenario(connection)
    commit(connection, scenario)
    tenant = scenario["owner"]["app_metadata"]["tenant_id"]
    artifact, version, template_hash = uuid4(), uuid4(), "b" * 64
    connection.execute("insert into public.governanca_artefatos"
        "(id,tenant_id,tipo_artefato,chave_estavel,descricao) values(%s,%s,'template',%s,'QA')",
        (artifact, tenant, "template.dfd." + uuid4().hex))
    connection.execute("insert into public.governanca_versoes"
        "(id,artefato_id,versao,status,payload,hash) values(%s,%s,1,'PUBLISHED',%s,%s)",
        (version, artifact, Jsonb({"documentos_suportados": ["dfd"]}), template_hash))
    source_hash, institutional = connection.execute(
        "select content_hash,institutional_snapshot from public.documentos_editor_revisoes "
        "where document_id=%s and revision=1", (scenario["doc"],)).fetchone()
    payload = b"native template target"
    target_hash = hashlib.sha256(payload).hexdigest()
    index = json.dumps({"schema": "gc-wordcraft-block-index/v1",
        "document_id": str(scenario["doc"]), "revision": 2,
        "content_hash": target_hash, "engine_manifest_sha256": "a" * 64,
        "blocos": [], "invalidacoes": [], "areas_nao_enderecaveis": []},
        sort_keys=True, separators=(",", ":")).encode()
    operation = uuid4()
    proof = {"schema": "gc-wordcraft-template-application/v1",
        "operationId": str(operation), "processId": str(scenario["process"]),
        "actorId": scenario["owner"]["sub"], "documentId": str(scenario["doc"]),
        "docKey": "dfd", "sourceRevision": 1, "sourceHash": source_hash,
        "sourceBundleHash": "c" * 64,
        "template": {"artifactId": str(artifact), "versionId": str(version),
                     "key": connection.execute("select chave_estavel from public.governanca_artefatos where id=%s",
                                               (artifact,)).fetchone()[0],
                     "version": 1, "hash": template_hash},
        "clausesUsed": [], "renderedTextHash": "d" * 64,
        "targetRevision": 2, "targetHash": target_hash,
        "engineManifestHash": "a" * 64, "officialEmission": False}
    return scenario, version, template_hash, payload, index, bytes(institutional), operation, proof


def apply(connection, data, *, operation=None, proof=None, role_name="service_role"):
    from psycopg.types.json import Jsonb
    scenario, version, template_hash, payload, index, institutional, original_operation, original_proof = data
    operation = operation or original_operation
    proof = original_proof if proof is None else proof
    with role(connection, role_name, scenario["owner"]):
        return connection.execute("select * from public.documento_editor_aplicar_template("
            + ",".join(["%s"] * 16) + ")", (scenario["doc"], scenario["process"], "dfd", 1,
            operation, payload, hashlib.sha256(payload).hexdigest(), "a" * 64,
            index, hashlib.sha256(index).hexdigest(), institutional,
            hashlib.sha256(institutional).hexdigest(), version, template_hash,
            Jsonb(proof), Jsonb(scenario["owner"]))).fetchone()


def test_application_is_atomic_lineage_bound_and_exact_retry_is_idempotent(template_db):
    data = fixture(template_db)
    first = apply(template_db, data)
    again = apply(template_db, data)
    assert first[:4] == again[:4]
    assert first[4] is False and again[4] is True
    assert first[8] == again[8] == "template_application"
    assert first[10] == again[10] == data[1]
    assert first[11] == again[11] == data[2]
    assert first[12] == again[12] == data[7]
    row = template_db.execute("select revision,index_mode,template_version_id,template_proof "
        "from public.documentos_editor_revisoes where document_id=%s order by revision desc limit 1",
        (data[0]["doc"],)).fetchone()
    assert row == (2, "template_application", data[1], data[7])


def test_stale_source_and_ambiguous_effective_template_roll_back_without_revision(template_db):
    import psycopg
    from psycopg.types.json import Jsonb
    data = fixture(template_db)
    bad = {**data[7], "sourceHash": "e" * 64}
    with pytest.raises(psycopg.ProgrammingError) as captured:
        apply(template_db, data, proof=bad)
    assert captured.value.sqlstate == "PT409"
    scenario = data[0]
    artifact = uuid4()
    template_db.execute("insert into public.governanca_artefatos"
        "(id,tenant_id,tipo_artefato,chave_estavel,descricao) values(%s,%s,'template',%s,'QA')",
        (artifact, scenario["owner"]["app_metadata"]["tenant_id"], "template.dfd." + uuid4().hex))
    template_db.execute("insert into public.governanca_versoes"
        "(artefato_id,versao,status,payload,hash) values(%s,1,'PUBLISHED',%s,%s)",
        (artifact, Jsonb({"documentos_suportados": ["dfd"]}), "f" * 64))
    with pytest.raises(psycopg.ProgrammingError) as captured:
        apply(template_db, data)
    assert captured.value.sqlstate == "PT409"
    assert template_db.execute("select count(*) from public.documentos_editor_revisoes "
        "where document_id=%s", (scenario["doc"],)).fetchone() == (1,)


def test_network_actor_cannot_call_rpc_or_mutate_template_lineage(template_db):
    import psycopg
    data = fixture(template_db)
    with pytest.raises(psycopg.errors.InsufficientPrivilege):
        apply(template_db, data, role_name="authenticated")
    apply(template_db, data)
    for statement in ("update public.documentos_editor_revisoes set template_proof='{}'",
                      "delete from public.documentos_editor_revisoes"):
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            with role(template_db, "service_role"):
                template_db.execute(statement)
