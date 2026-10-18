"""Institutional linkage. Engine/transport stubs are explicit; SQL tests separate."""
import hashlib
import io
import json
from uuid import uuid4
from zipfile import ZipFile

import pytest

from src import documentos_editor as owner
from tests.test_documentos_editor import Query, setup


@pytest.fixture
def institutional(setup, monkeypatch):
    service, state, checkpoint = setup
    state["persist"] = True
    tenant = state["context"]["app_metadata"]["tenant_id"]
    secretary, person, portaria = (str(uuid4()) for _ in range(3))
    state["head"]["tenant_id"] = tenant
    state["process"] = {"id": state["head"]["processo_id"], "tenant_id": tenant, "secretaria_id": secretary,
        "criado_em": "2026-01-20T12:00:00Z", "documentos": {"dfd": "Texto original **sintético**"},
        "dados": {"signatarios_escolhidos": {"dfd": [{"servidor_id": person, "funcao": "EQUIPE_PLANEJAMENTO"}]}}}
    state["catalogs"] = {
        "secretarias": [{"id": secretary, "tenant_id": tenant, "nome": "Secretaria Sintética", "ativo": True,
            "cabecalho": "CABEÇALHO AUTORIZADO", "rodape": "RODAPÉ AUTORIZADO",
            "cabecalho_img": "data:image/png;base64,LOGO-ORIGINAL",
            "rodape_img": "data:image/png;base64,RODAPE-ORIGINAL",
            "marca_img": "data:image/png;base64,MARCA-ORIGINAL",
            "cabecalho_pct": 14, "rodape_pct": 10, "padrao": False}],
        "servidores": [{"id": person, "tenant_id": tenant, "nome": "Ana Sintética", "cargo": "Analista", "ativo": True}],
        "servidor_funcoes": [],
        "portarias": [{"id": portaria, "tenant_id": tenant, "secretaria_id": secretary, "tipo": "EQUIPE_PLANEJAMENTO",
            "numero": "007", "ano": 2026, "status": "ATIVA", "data_publicacao": "2026-01-01",
            "data_inicio_vigencia": "2026-01-01", "data_fim_vigencia": None}],
        "portaria_membros": [{"tenant_id": tenant, "portaria_id": portaria, "servidor_id": person,
            "funcao": "EQUIPE_PLANEJAMENTO", "ativo": True}],
    }
    old_user, old_server = owner.db.cliente_do_usuario(), owner.db._cliente()
    state["catalog_reads"] = []
    state["history"] = {1: {**state["row"], "revision": 1}}

    class Catalog(Query):
        def eq(self, key, value):
            self.result = [row for row in self.result if row.get(key) == value]
            return self

    class Revisions(Query):
        def eq(self, key, value):
            if key in {"revision", "operation_id"}:
                self.result = [row for row in self.result if row.get(key) == value]
            return self

    class User:
        def rpc(self, name, params): return old_user.rpc(name, params)
        def table(self, name):
            if name in state["catalogs"]:
                state["catalog_reads"].append(name)
                return Catalog(state["catalogs"][name])
            if name == "documentos_editor_revisoes":
                return Revisions(list(state["history"].values()))
            return old_user.table(name)

    class Server:
        def rpc(self, name, params):
            result = old_server.rpc(name, params)
            result.result[0]["institutional_snapshot_sha256"] = params["p_institutional_snapshot_sha256"]
            state["row"].update(institutional_snapshot=params["p_institutional_snapshot"],
                institutional_snapshot_sha256=params["p_institutional_snapshot_sha256"])
            state["history"][result.result[0]["revision"]] = dict(state["row"])
            return result

    monkeypatch.setattr(owner.db, "cliente_do_usuario", lambda: User())
    monkeypatch.setattr(owner.db, "_cliente", lambda: Server())
    return service, state, checkpoint


def create(institutional):
    service, state, checkpoint = institutional
    return service.criar(processo_id=state["process"]["id"], tipo="dfd", payload=checkpoint.content, operation_id=str(uuid4()))


def test_snapshot_uses_authenticated_backend_and_canonical_eligibility_without_approval(institutional):
    document = create(institutional)
    value = document.institutional_snapshot
    assert value["phase"] == "draft_reference" and document.status == "rascunho"
    assert value["application"] == "reference_only"
    assert value["reference_date"] == "2026-01-20"
    assert value["identity"]["origem"] == "secretaria"
    assert value["signatories"][0]["nome_snapshot"] == "Ana Sintética"
    assert value["signatories"][0]["portaria_numero_snapshot"] == "007/2026"
    assert "ANA SINTÉTICA" in value["signature_block"]
    assert document.institutional_snapshot_hash == hashlib.sha256(owner._snapshot_bytes(value)).hexdigest()


def test_later_registry_changes_do_not_reinterpret_open_export_or_next_checkpoint(institutional, monkeypatch):
    service, state, checkpoint = institutional
    document = create(institutional)
    digest = document.institutional_snapshot_hash
    frozen = owner._snapshot_bytes(document.institutional_snapshot)
    reads = len(state["catalog_reads"])
    state["catalogs"]["secretarias"][0].update(
        cabecalho="OUTRA IDENTIDADE", rodape="OUTRO RODAPÉ",
        cabecalho_img="data:image/png;base64,LOGO-NOVA",
        rodape_img="data:image/png;base64,RODAPE-NOVO",
        marca_img="data:image/png;base64,MARCA-NOVA",
        cabecalho_pct=25, rodape_pct=20)
    state["catalogs"]["servidores"][0].update(nome="Outra Pessoa", cargo="Outro", ativo=False)
    state["catalogs"]["portarias"][0].update(numero="999", status="REVOGADA")
    reopened = service.abrir(document.id)
    assert reopened.institutional_snapshot_hash == digest
    assert owner._snapshot_bytes(reopened.institutional_snapshot) == frozen
    assert reopened.institutional_snapshot["identity"]["identidade"]["cabecalho_img"].endswith("LOGO-ORIGINAL")
    assert reopened.institutional_snapshot["signatories"][0]["nome_snapshot"] == "Ana Sintética"
    monkeypatch.setattr(owner, "exportar", lambda *args, **kwargs: b"%PDF-synthetic")
    artifact = service.exportar(document.id, expected_revision=1, content_hash=document.content_hash, formato="pdf")
    assert artifact.institutional_snapshot_hash == digest
    receipt = service.checkpoint(document.id, checkpoint)
    assert receipt.institutional_snapshot_hash == digest and receipt.revision == 2
    after_checkpoint = service.abrir(document.id)
    assert owner._snapshot_bytes(after_checkpoint.institutional_snapshot) == frozen
    assert len(state["catalog_reads"]) == reads


@pytest.mark.parametrize("change", ["inactive", "revoked", "wrong_scope", "ambiguous"])
def test_new_snapshot_refuses_ineligible_or_ambiguous_backend_designations(institutional, change):
    service, state, _ = institutional
    if change == "inactive":
        state["catalogs"]["servidores"][0]["ativo"] = False
    elif change == "revoked":
        state["catalogs"]["portarias"][0]["status"] = "REVOGADA"
    elif change == "wrong_scope":
        state["catalogs"]["servidores"][0]["tenant_id"] = str(uuid4())
    else:
        state["catalogs"]["portarias"].append({**state["catalogs"]["portarias"][0], "id": str(uuid4()), "numero": "008"})
    with pytest.raises(owner.ErroDocumento, match="contexto institucional"):
        create(institutional)
    assert state["server_calls"] == []


def test_jwt_metadata_cannot_supply_branding_or_signatory_names(institutional):
    _, state, _ = institutional
    state["context"]["app_metadata"].update(cabecalho="FORGED", nome_snapshot="FORGED")
    document = create(institutional)
    assert "FORGED" not in json.dumps(document.institutional_snapshot)


def test_markdown_import_applies_the_same_frozen_branding_and_signature_to_canonical_docx(institutional, monkeypatch):
    service, state, checkpoint = institutional
    imported = []
    monkeypatch.setattr(owner, "importar_docx", lambda data, **kwargs: imported.append(data) or checkpoint.content)
    document = service.importar_legado(processo_id=state["process"]["id"], tipo="dfd", formato="markdown", operation_id=str(uuid4()))
    with ZipFile(io.BytesIO(imported[0])) as archive:
        assert "CABEÇALHO AUTORIZADO" in archive.read("word/header1.xml").decode()
        body = archive.read("word/document.xml").decode()
        assert "ANA SINTÉTICA" in body and "007/2026" in body
    assert document.institutional_snapshot["application"] == "applied_by_govconnect_docx"
    assert document.status == "rascunho"


def test_restore_carries_recorded_source_context_and_cites_source_revision_hash(institutional, monkeypatch):
    service, state, checkpoint = institutional
    document = create(institutional)
    digest = document.institutional_snapshot_hash
    receipt = service.restaurar(document.id, source_revision=1, expected_revision=1, operation_id=str(uuid4()))
    assert receipt.revision == 2 and receipt.restored_from_revision == 1
    assert receipt.institutional_snapshot_hash == digest
    monkeypatch.setattr(owner, "exportar", lambda *args, **kwargs: b"%PDF-synthetic")
    artifact = service.exportar(document.id, expected_revision=2, content_hash=document.content_hash, formato="pdf")
    assert artifact.restored_from_revision == 1 and artifact.restored_source_hash == checkpoint.content_hash
    assert artifact.institutional_snapshot_hash == digest


def test_unknown_historical_context_stays_unknown_on_open(institutional):
    service, state, _ = institutional
    # The pre-migration row has neither column populated. Opening may validate
    # native bytes today; it does not invent past institutional facts.
    document = service.abrir(state["head"]["id"])
    assert document.institutional_snapshot is None and document.institutional_snapshot_hash is None
    assert state["catalog_reads"] == []


def test_initial_retry_reuses_recorded_snapshot_after_registry_changes(institutional):
    service, state, checkpoint = institutional
    operation = str(uuid4())
    document = service.criar(processo_id=state["process"]["id"], tipo="dfd", payload=checkpoint.content, operation_id=operation)
    reads = len(state["catalog_reads"])
    state["catalogs"]["servidores"][0]["ativo"] = False
    retried = service.criar(processo_id=state["process"]["id"], tipo="dfd", payload=checkpoint.content, operation_id=operation)
    assert retried.institutional_snapshot_hash == document.institutional_snapshot_hash
    assert len(state["catalog_reads"]) == reads
