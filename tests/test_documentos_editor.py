"""Owner contract tests with transport/native stubs; real engine/RLS are separate."""
from dataclasses import replace
import hashlib
import io
import json
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import pytest
from zipfile import ZipFile

from src import documentos_editor as owner
from src.wordcraft_protocol import Checkpoint


class Query:
    def __init__(self, result):
        self.result = result

    def execute(self):
        if isinstance(self.result, Exception):
            raise self.result
        return SimpleNamespace(data=self.result)

    def select(self, *args): return self
    def eq(self, *args):
        if args[0] == "operation_id" and isinstance(self.result, list):
            self.result = [row for row in self.result if row.get("operation_id") == args[1]]
        return self
    def limit(self, *args): return self
    def order(self, *args, **kwargs): return self


@pytest.fixture
def setup(monkeypatch):
    payload = json.dumps({"schema": owner.SCHEMA, "document": {"body": [
        {"kind": "para", "text": "Synthetic unit paragraph", "runs": [{"len": 24}]}], "parts": {}},
        "media": {}, "passthrough": {}}).encode()
    identity = {"sub": str(uuid4()), "role": "authenticated", "app_metadata": {"tenant_id": str(uuid4())}}
    head = dict(id=str(uuid4()), processo_id=str(uuid4()), tipo="dfd", revision=1,
                content_hash=hashlib.sha256(payload).hexdigest(), status="rascunho", tenant_id=identity["app_metadata"]["tenant_id"])
    checkpoint = Checkpoint(str(uuid4()), 1, head["content_hash"], payload)
    state = {"context": identity, "server_calls": [], "native_calls": [], "head": head}
    row = dict(payload="\\x" + payload.hex(), content_hash=head["content_hash"],
               editor_schema_version=owner.SCHEMA, wordcraft_commit=owner.UPSTREAM,
               engine_build_sha256=None, validation_provenance="legacy_unrecorded")
    state["row"] = row

    class User:
        def rpc(self, name, params):
            assert name == "documento_editor_contexto" and params == {}
            return Query(state["context"])

        def table(self, name):
            if name == "processos":
                return Query([state.get("process", {"id": head["processo_id"], "tenant_id": head["tenant_id"],
                    "secretaria_id": None, "criado_em": "2026-01-20T12:00:00Z", "dados": {},
                    "documentos": {"dfd": "Original\r\n**legado**"}})])
            if name == "documentos_editor":
                return Query([state["head"]])
            return Query([state["row"]] if name == "documentos_editor_revisoes" else [])

    class Server:
        def rpc(self, name, params):
            assert name == "documento_editor_checkpoint"
            state["server_calls"].append(params)
            result = dict(document_id=params["p_document"], revision=params["p_expected_revision"] + 1,
                          content_hash=params["p_content_hash"], operation_id=params["p_operation"], replayed=False,
                          engine_build_sha256=params["p_engine_build_sha256"],
                          validation_provenance="server_manifest_sha256",
                          block_index_sha256=params["p_block_index_sha256"], index_mode=params["p_index_mode"],
                          restored_from_revision=params["p_restored_from_revision"],
                          institutional_snapshot_sha256=params["p_institutional_snapshot_sha256"],
                          original_hash=hashlib.sha256(bytes.fromhex(params["p_original_payload"][2:])).hexdigest()
                            if params["p_original_payload"] else None)
            if state.get("persist"):
                state["head"] = dict(head, id=params["p_document"], revision=result["revision"], content_hash=result["content_hash"])
                state["row"] = dict(payload=params["p_payload"], content_hash=result["content_hash"],
                    editor_schema_version=owner.SCHEMA, wordcraft_commit=owner.UPSTREAM,
                    engine_build_sha256=params["p_engine_build_sha256"], validation_provenance="server_manifest_sha256",
                    block_index=params["p_block_index"], block_index_sha256=params["p_block_index_sha256"],
                    index_mode=params["p_index_mode"], restored_from_revision=params["p_restored_from_revision"],
                    original_format=params["p_original_format"], original_payload=params["p_original_payload"],
                    original_hash=result["original_hash"], conversion_report=params["p_conversion_report"])
                state["row"].update(institutional_snapshot=params["p_institutional_snapshot"],
                    institutional_snapshot_sha256=params["p_institutional_snapshot_sha256"])
                state["row"].update(operation_id=params["p_operation"], revision=result["revision"])
            return Query(state.get("server_result", [result]))

    monkeypatch.setattr(owner.db, "cliente_do_usuario", lambda: User())
    monkeypatch.setattr(owner.db, "_cliente", lambda: Server())
    monkeypatch.setattr(owner, "validar", lambda value, **kwargs: state["native_calls"].append(value))
    monkeypatch.setattr(owner.blocos, "validar", lambda value, **kwargs: state["native_calls"].append(value))
    service = owner.DocumentoService(node=Path("C:/server/node.exe"), bundle=Path("C:/server/bundle"), manifest_sha256="a" * 64)
    return service, state, checkpoint


def test_commit_uses_verified_context_and_returns_only_correlated_receipt(setup):
    service, state, checkpoint = setup
    receipt = service.checkpoint(state["head"]["id"], checkpoint)
    assert receipt.revision == 2 and receipt.request_id == checkpoint.request_id
    assert state["server_calls"][0]["p_claims"] is state["context"]
    assert state["server_calls"][0]["p_process"] == state["head"]["processo_id"]
    assert state["native_calls"] and all(value == checkpoint.content for value in state["native_calls"])
    assert state["server_calls"][0]["p_engine_build_sha256"] == "a" * 64
    assert receipt.engine_build == "a" * 64 and receipt.validation_provenance == "server_manifest_sha256"
    assert "payload" not in repr(receipt)


def test_open_rechecks_native_bytes_and_hash(setup):
    service, state, checkpoint = setup
    document = service.abrir(state["head"]["id"])
    assert document.payload == checkpoint.content and document.revision == 1
    assert document.engine_build is None and document.validation_provenance == "legacy_unrecorded"
    assert checkpoint.content.decode() not in repr(document)
    assert state["native_calls"] == [checkpoint.content]


def test_listar_processo_reusa_sessao_e_revisao_autorizadas(setup):
    service, state, checkpoint = setup
    documents = service.listar_processo(state["head"]["processo_id"])
    assert len(documents) == 1
    assert documents[0].id == state["head"]["id"]
    assert documents[0].payload == checkpoint.content


@pytest.mark.parametrize("status", ["aprovado", "emitido"])
def test_open_rehydrates_native_approval_for_every_immutable_head_status(setup, monkeypatch, status):
    service, state, _ = setup
    state["head"]["status"] = status
    proof = object()
    monkeypatch.setattr(service, "_approval", lambda user, document: proof)
    document = service.abrir(state["head"]["id"])
    assert document.status == status and document.approval is proof


def test_texto_aprovado_exige_prova_indice_e_cobertura(setup, monkeypatch):
    service, state, checkpoint = setup
    document = SimpleNamespace(id=state["head"]["id"], tipo="dfd",
        status="aprovado", approval=object(), index=object(),
        payload=checkpoint.content)
    monkeypatch.setattr(service, "abrir", lambda document_id: document)
    monkeypatch.setattr(owner.blocos, "projetar_documento", lambda *a, **k:
        SimpleNamespace(apto_analise=True, texto_analise="Projeção nativa aprovada"))
    assert service.texto_aprovado(document.id) == ("dfd", "Projeção nativa aprovada")
    document.status = "rascunho"
    with pytest.raises(owner.ErroDocumento, match="aprovação"):
        service.texto_aprovado(document.id)


def test_no_authenticated_client_does_not_call_engine_or_private_rpc(setup, monkeypatch):
    service, state, checkpoint = setup
    monkeypatch.setattr(owner.db, "cliente_do_usuario", lambda: None)
    with pytest.raises(owner.AcessoNegado):
        service.checkpoint(state["head"]["id"], checkpoint)
    assert state["native_calls"] == state["server_calls"] == []


def test_unverified_or_extra_context_is_rejected(setup):
    service, state, checkpoint = setup
    state["context"] = {**state["context"], "user_metadata": {"papel": "admin"}}
    with pytest.raises(owner.AcessoNegado):
        service.checkpoint(state["head"]["id"], checkpoint)
    assert state["native_calls"] == state["server_calls"] == []


def test_bad_checkpoint_hash_never_reaches_the_engine_or_database(setup):
    service, state, checkpoint = setup
    with pytest.raises(owner.ErroDocumento):
        service.checkpoint(state["head"]["id"], replace(checkpoint, content=b"changed"))
    assert state["native_calls"] == state["server_calls"] == []


def test_native_failure_never_reaches_commit(setup, monkeypatch):
    service, state, checkpoint = setup
    def fail(*args, **kwargs):
        raise RuntimeError("sensitive-shaped error must not escape")
    monkeypatch.setattr(owner, "validar", fail)
    with pytest.raises(owner.ErroDocumento, match="motor") as caught:
        service.checkpoint(state["head"]["id"], checkpoint)
    assert "sensitive" not in str(caught.value) and state["server_calls"] == []


def test_conflict_is_not_an_ack_and_does_not_echo_api_body(setup):
    service, state, checkpoint = setup
    class ApiConflict(Exception):
        code = "40001"
    state["server_result"] = ApiConflict("do not echo a document body")
    with pytest.raises(owner.ConflitoDocumento) as caught:
        service.checkpoint(state["head"]["id"], checkpoint)
    assert "body" not in str(caught.value)


def test_mismatched_commit_response_is_rejected(setup):
    service, state, checkpoint = setup
    state["server_result"] = [dict(document_id=state["head"]["id"], revision=99,
                                   content_hash=checkpoint.content_hash, operation_id=checkpoint.request_id, replayed=False)]
    with pytest.raises(owner.ErroDocumento, match="commit"):
        service.checkpoint(state["head"]["id"], checkpoint)


def test_corrupt_persisted_bytes_are_not_loaded(setup):
    service, state, _ = setup
    state["row"]["payload"] = "\\x00"
    with pytest.raises(owner.ErroDocumento, match="Hash"):
        service.abrir(state["head"]["id"])
    assert state["native_calls"] == []


def test_export_is_bound_to_the_exact_authorized_persisted_revision(setup, monkeypatch):
    service, state, checkpoint = setup
    seen = []
    def render(payload, **kwargs):
        seen.append((payload, kwargs))
        return b"%PDF-synthetic artifact"
    monkeypatch.setattr(owner, "exportar", render)
    artifact = service.exportar(state["head"]["id"], expected_revision=1,
                                content_hash=checkpoint.content_hash, formato="pdf")
    assert seen[0][0] == checkpoint.content and artifact.source_hash == checkpoint.content_hash
    assert artifact.revision == 1 and artifact.engine_build == "a" * 64
    assert artifact.source_engine_build is None and artifact.source_validation_provenance == "legacy_unrecorded"
    assert artifact.content_hash == hashlib.sha256(artifact.payload).hexdigest()
    assert "synthetic artifact" not in repr(artifact)


def test_approved_package_reuses_exact_exports_and_records_auditable_manifest(setup, monkeypatch):
    service, state, checkpoint = setup
    process = state["head"]["processo_id"]
    approval = SimpleNamespace(id=str(uuid4()), institutional_snapshot_hash="b" * 64)
    documents = tuple(SimpleNamespace(id=str(uuid4()), processo_id=process, tipo=tipo,
        revision=index, content_hash=hashlib.sha256(tipo.encode()).hexdigest(),
        status="aprovado", approval=approval)
        for index, tipo in enumerate(("dfd", "etp"), 1))
    monkeypatch.setattr(service, "listar_processo", lambda value: documents)
    calls = []
    def export(document_id, *, expected_revision, content_hash, formato):
        payload = f"{document_id}:{expected_revision}:{formato}".encode()
        calls.append((document_id, expected_revision, content_hash, formato))
        return owner.Artefato(document_id, expected_revision, content_hash, formato,
            hashlib.sha256(payload).hexdigest(), "a" * 64, payload)
    monkeypatch.setattr(service, "exportar", export)
    package = service.empacotar_aprovados(process, tipos=("dfd", "etp"), formato="pdf")
    assert package.manifest["official_emission"] is False
    assert [entry["tipo"] for entry in package.manifest["documents"]] == ["dfd", "etp"]
    assert [call[2] for call in calls] == [doc.content_hash for doc in documents]
    assert package.content_hash == hashlib.sha256(package.payload).hexdigest()
    with ZipFile(io.BytesIO(package.payload)) as archive:
        assert archive.namelist() == ["dfd-r1.pdf", "etp-r2.pdf", "manifest.json"]
        assert json.loads(archive.read("manifest.json")) == package.manifest


def test_package_refuses_a_draft_before_export(setup, monkeypatch):
    service, state, _ = setup
    draft = SimpleNamespace(id=str(uuid4()), processo_id=state["head"]["processo_id"],
        tipo="dfd", revision=1, content_hash="a" * 64, status="rascunho", approval=None)
    monkeypatch.setattr(service, "listar_processo", lambda value: (draft,))
    monkeypatch.setattr(service, "exportar", lambda *a, **k: pytest.fail("draft export"))
    with pytest.raises(owner.ErroDocumento, match="sem aprovação"):
        service.empacotar_aprovados(draft.processo_id, tipos=("dfd",), formato="docx")


def test_official_emission_binds_both_packages_and_accepts_only_exact_receipt(setup, monkeypatch):
    service, state, _ = setup
    process, operation = state["head"]["processo_id"], str(uuid4())
    state["process"] = {"id": process, "dados": {}}
    monkeypatch.setattr(service, "listar_processo", lambda value: ())
    monkeypatch.setattr(owner.config, "sequencia_do_processo", lambda dados, docs: ["dfd"])
    approval, snapshot = str(uuid4()), "b" * 64
    def package(fmt):
        payload = (fmt + " package").encode()
        artifact = hashlib.sha256((fmt + " artifact").encode()).hexdigest()
        manifest = {"documents": [{"tipo": "dfd", "document_id": state["head"]["id"],
            "revision": 1, "source_sha256": state["head"]["content_hash"],
            "approval_id": approval, "approval_snapshot_sha256": snapshot,
            "artifact_sha256": artifact, "engine_manifest_sha256": "a" * 64,
            "file": f"dfd-r1.{fmt}"}]}
        return owner.PacoteArtefatos(process, fmt, hashlib.sha256(payload).hexdigest(), manifest, payload)
    packages = {fmt: package(fmt) for fmt in ("docx", "pdf")}
    monkeypatch.setattr(service, "empacotar_aprovados",
        lambda processo_id, *, tipos, formato: packages[formato])
    calls = []
    result = {"emission_id": str(uuid4()), "processo_id": process,
        "operation_id": operation, "docx_sha256": packages["docx"].content_hash,
        "pdf_sha256": packages["pdf"].content_hash, "event_id": str(uuid4()),
        "replayed": False}
    monkeypatch.setattr(owner.db, "_cliente", lambda: SimpleNamespace(
        # PostgREST represents a RETURNS TABLE RPC as a one-row JSON array.
        rpc=lambda name, params: calls.append((name, params)) or Query([result])))
    emission = service.emitir_aprovados(process, tipos=("dfd",), operation_id=operation)
    assert emission.id == result["emission_id"] and emission.replayed is False
    assert calls[0][0] == "documento_editor_emitir"
    params = calls[0][1]
    assert params["p_manifest"]["official_emission"] is True
    assert params["p_manifest"]["packages"]["pdf"]["sha256"] == packages["pdf"].content_hash
    assert params["p_documents"][0]["approval_id"] == approval
    assert bytes.fromhex(params["p_docx"][2:]) == packages["docx"].payload


def test_official_emission_refuses_packages_from_different_sources(setup, monkeypatch):
    service, state, _ = setup
    process = state["head"]["processo_id"]
    state["process"] = {"id": process, "dados": {}}
    monkeypatch.setattr(service, "listar_processo", lambda value: ())
    monkeypatch.setattr(owner.config, "sequencia_do_processo", lambda dados, docs: ["dfd"])
    def package(fmt):
        payload = fmt.encode()
        manifest = {"documents": [{"tipo": "dfd", "document_id": state["head"]["id"],
            "revision": 1 if fmt == "docx" else 2,
            "source_sha256": state["head"]["content_hash"], "approval_id": str(uuid4()),
            "approval_snapshot_sha256": "b" * 64, "artifact_sha256": "c" * 64,
            "engine_manifest_sha256": "a" * 64, "file": f"dfd.{fmt}"}]}
        return owner.PacoteArtefatos(process, fmt, hashlib.sha256(payload).hexdigest(), manifest, payload)
    monkeypatch.setattr(service, "empacotar_aprovados",
        lambda processo_id, *, tipos, formato: package(formato))
    monkeypatch.setattr(owner.db, "_cliente", lambda: pytest.fail("RPC must not run"))
    with pytest.raises(owner.ConflitoDocumento, match="mesma revisão"):
        service.emitir_aprovados(process, tipos=("dfd",), operation_id=str(uuid4()))


@pytest.mark.parametrize("dados,tipos,allowed", [
    ({"modelo_execucao": "Sistema de Registro de Preços (SRP)"},
     ("dfd", "etp", "tr", "edital", "arp"), True),
    ({"modelo_execucao": "Entrega integral"},
     ("dfd", "etp", "tr", "edital"), True),
    ({"modelo_execucao": "Entrega integral"},
     ("dfd", "etp", "tr", "edital", "arp"), False),
    ({"modelo_execucao": "Sistema de Registro de Preços (SRP)"},
     ("dfd", "etp", "tr", "edital"), False),
])
def test_official_emission_derives_arp_from_server_process_form(setup, monkeypatch,
                                                               dados, tipos, allowed):
    service, state, _ = setup
    process = state["head"]["processo_id"]
    state["process"] = {"id": process, "dados": dados}
    monkeypatch.setattr(service, "listar_processo", lambda value: ())
    class PackagingReached(RuntimeError):
        pass
    monkeypatch.setattr(service, "empacotar_aprovados", lambda *a, **k:
        (_ for _ in ()).throw(PackagingReached()))
    if allowed:
        # Reaching packaging proves the owner accepted the canonical set.
        with pytest.raises(PackagingReached):
            service.emitir_aprovados(process, tipos=tipos, operation_id=str(uuid4()))
    else:
        with pytest.raises(owner.ErroDocumento, match="instrumentos do processo"):
            service.emitir_aprovados(process, tipos=tipos, operation_id=str(uuid4()))


def test_persisted_emission_reopens_exact_bytes_without_export(setup, monkeypatch):
    service, state, _ = setup
    process, emission_id, operation, event_id = (state["head"]["processo_id"],
        str(uuid4()), str(uuid4()), str(uuid4()))
    payloads = {"docx": b"persisted docx zip", "pdf": b"persisted pdf zip"}
    hashes = {fmt: hashlib.sha256(payload).hexdigest() for fmt, payload in payloads.items()}
    manifest = {"schema": "gc-wordcraft-official-emission/v1", "official_emission": True,
        "processo_id": process, "engine_manifest_sha256": "a" * 64, "documents": [],
        "packages": {fmt: {"sha256": hashes[fmt], "bytes": len(payloads[fmt])}
                     for fmt in payloads}}
    row = {"id": emission_id, "processo_id": process, "operation_id": operation,
        "engine_manifest_sha256": "a" * 64, "manifest": manifest,
        "docx_package": "\\x" + payloads["docx"].hex(), "docx_sha256": hashes["docx"],
        "pdf_package": "\\x" + payloads["pdf"].hex(), "pdf_sha256": hashes["pdf"],
        "criado_em": "2026-10-16T00:00:00Z"}
    event = {"id": event_id, "ator": state["context"]["sub"],
             "payload": {"operation_id": operation, "official_emission": True}}
    class User:
        def rpc(self, *args): return Query(state["context"])
        def table(self, name): return Query([row] if name == "documentos_editor_emissoes" else [event])
    monkeypatch.setattr(owner.db, "cliente_do_usuario", lambda: User())
    monkeypatch.setattr(service, "empacotar_aprovados", lambda *a, **k: pytest.fail("must not reexport"))
    emission = service.emissao_atual(process)
    assert emission.id == emission_id and emission.event_id == event_id
    assert emission.docx.payload == payloads["docx"] and emission.pdf.payload == payloads["pdf"]


def test_stale_export_does_not_execute_the_exporter(setup, monkeypatch):
    service, state, checkpoint = setup
    monkeypatch.setattr(owner, "exportar", lambda *args, **kwargs: pytest.fail("stale revision"))
    with pytest.raises(owner.ConflitoDocumento):
        service.exportar(state["head"]["id"], expected_revision=2,
                         content_hash=checkpoint.content_hash, formato="pdf")


def test_recorded_validation_build_survives_open_and_export_with_a_new_runtime(setup, monkeypatch):
    service, state, checkpoint = setup
    state["row"].update(engine_build_sha256="b" * 64, validation_provenance="server_manifest_sha256")
    document = service.abrir(state["head"]["id"])
    monkeypatch.setattr(owner, "exportar", lambda *args, **kwargs: b"%PDF-export by current runtime")
    artifact = service.exportar(document.id, expected_revision=1, content_hash=checkpoint.content_hash, formato="pdf")
    assert document.engine_build == artifact.source_engine_build == "b" * 64
    assert artifact.source_validation_provenance == "server_manifest_sha256"
    assert artifact.engine_build == "a" * 64
    assert artifact.source_hash == document.content_hash


@pytest.mark.parametrize("build,provenance", [(None, "server_manifest_sha256"),
    ("a" * 64, "legacy_unrecorded"), ("A" * 64, "server_manifest_sha256"), (None, None)])
def test_incoherent_persisted_provenance_fails_before_native_load(setup, build, provenance):
    service, state, _ = setup
    state["row"].update(engine_build_sha256=build, validation_provenance=provenance)
    with pytest.raises(owner.ErroDocumento, match="Proveniência"):
        service.abrir(state["head"]["id"])
    assert state["native_calls"] == []


def test_runtime_manifest_is_not_taken_from_verified_jwt_metadata(setup):
    service, state, checkpoint = setup
    state["context"]["app_metadata"]["engine_build_sha256"] = "b" * 64
    receipt = service.checkpoint(state["head"]["id"], checkpoint)
    assert receipt.engine_build == state["server_calls"][0]["p_engine_build_sha256"] == "a" * 64


def test_receipt_with_another_build_is_not_accepted_as_an_ack(setup):
    service, state, checkpoint = setup
    state["server_result"] = [dict(document_id=state["head"]["id"], revision=2,
        content_hash=checkpoint.content_hash, operation_id=checkpoint.request_id, replayed=True,
        engine_build_sha256="b" * 64, validation_provenance="server_manifest_sha256")]
    with pytest.raises(owner.ErroDocumento, match="commit"):
        service.checkpoint(state["head"]["id"], checkpoint)


@pytest.mark.parametrize("manifest", [None, "", "A" * 64, "a" * 63, 42])
def test_invalid_trusted_manifest_is_rejected_when_configuring_the_owner(manifest):
    with pytest.raises(owner.ErroDocumento, match="Manifesto"):
        owner.DocumentoService(node=Path("C:/server/node.exe"), bundle=Path("C:/server/bundle"),
                               manifest_sha256=manifest)


def test_commit_persists_derived_index_and_keeps_only_conservative_identities(setup):
    service, state, checkpoint = setup
    state["persist"] = True
    first = service.checkpoint(state["head"]["id"], checkpoint)
    document = service.abrir(state["head"]["id"])
    assert first.index_mode == document.index_mode == "rebuilt_missing_index"
    initial_id = document.index.blocos[0].block_id
    value = json.loads(checkpoint.content)
    value["document"]["body"].append({"kind": "para", "text": "Inserido", "runs": [{"len": 8}]})
    content = json.dumps(value).encode()
    next_checkpoint = Checkpoint(str(uuid4()), 2, hashlib.sha256(content).hexdigest(), content)
    receipt = service.checkpoint(document.id, next_checkpoint)
    assert receipt.index_mode == "reconciled"
    assert service.abrir(document.id).index.blocos[0].block_id == initial_id


def test_build_change_explicitly_rebuilds_index_and_invalidates_known_previous_ids(setup):
    service, state, checkpoint = setup
    state["persist"] = True
    service.checkpoint(state["head"]["id"], checkpoint)
    old = service.abrir(state["head"]["id"])
    next_service = owner.DocumentoService(node=Path("C:/server/node.exe"), bundle=Path("C:/server/bundle"), manifest_sha256="b" * 64)
    receipt = next_service.checkpoint(old.id, replace(checkpoint, request_id=str(uuid4()), expected_revision=2))
    document = next_service.abrir(old.id)
    assert receipt.index_mode == "rebuilt_build"
    assert document.index.blocos[0].block_id != old.index.blocos[0].block_id
    assert document.index.invalidacoes == (owner.blocos.Invalidacao(old.index.blocos[0].block_id, "build_alterado"),)


def test_markdown_import_reads_and_preserves_authorized_legacy_bytes_and_uses_canonical_docx(setup, monkeypatch):
    import io
    from zipfile import ZipFile
    service, state, checkpoint = setup
    state["persist"] = True
    imported = []
    monkeypatch.setattr(owner, "importar_docx", lambda data, **kwargs: imported.append(data) or checkpoint.content)
    document = service.importar_legado(processo_id=state["head"]["processo_id"], tipo="dfd",
        operation_id=str(uuid4()), formato="markdown")
    source = service.original(document.id, 1)
    assert source.payload == b"Original\r\n**legado**"
    assert source.content_hash == hashlib.sha256(source.payload).hexdigest()
    assert source.relatorio["fidelity"] == "pending_manual_review"
    assert source.relatorio["pipeline"] == "govconnect_docx_wordcraft"
    with ZipFile(io.BytesIO(imported[0])) as package:
        xml = package.read("word/document.xml").decode()
        assert "DOCUMENTO DE FORMALIZAÇÃO DA DEMANDA" in xml and "legado" in xml
    assert state["server_calls"][0]["p_original_format"] == "markdown"


def test_docx_import_preserves_uploaded_original_and_never_uses_claimed_index_or_source(setup, monkeypatch):
    service, state, checkpoint = setup
    state["persist"] = True
    source = b"Synthetic DOCX fixture; importer is explicitly stubbed here"
    monkeypatch.setattr(owner, "importar_docx", lambda data, **kwargs: checkpoint.content if data == source else pytest.fail("different bytes"))
    document = service.importar_legado(processo_id=state["head"]["processo_id"], tipo="dfd",
        operation_id=str(uuid4()), formato="docx", original_docx=source)
    assert service.original(document.id, 1).payload == source
    with pytest.raises(TypeError):
        service.checkpoint(document.id, checkpoint, index={"forged": True})


def test_failed_native_import_leaves_original_process_and_revision_store_untouched(setup, monkeypatch):
    service, state, _ = setup
    def refused(*args, **kwargs):
        raise RuntimeError("private source body should not escape")
    monkeypatch.setattr(owner, "importar_docx", refused)
    with pytest.raises(owner.ErroDocumento, match="original legado preservado") as error:
        service.importar_legado(processo_id=state["head"]["processo_id"], tipo="dfd",
            operation_id=str(uuid4()), formato="docx", original_docx=b"synthetic")
    assert "private" not in str(error.value) and state["server_calls"] == []


def test_restore_uses_authorized_historical_bytes_and_returns_new_cas_revision(setup):
    service, state, checkpoint = setup
    state["head"]["revision"] = 2
    receipt = service.restaurar(state["head"]["id"], source_revision=1, expected_revision=2, operation_id=str(uuid4()))
    assert receipt.revision == 3 and receipt.restored_from_revision == 1
    assert bytes.fromhex(state["server_calls"][0]["p_payload"][2:]) == checkpoint.content
    assert state["server_calls"][0]["p_original_payload"] is None


def test_index_hash_corruption_is_rejected_before_any_mutation(setup):
    service, state, checkpoint = setup
    state["row"].update(block_index="\\x7b7d", block_index_sha256="b" * 64, index_mode="initial")
    with pytest.raises(owner.ErroDocumento, match="Índice"):
        service.checkpoint(state["head"]["id"], checkpoint)
    assert state["server_calls"] == []


def test_import_retry_uses_the_exact_committed_checkpoint_without_reconverting(setup, monkeypatch):
    service, state, checkpoint = setup
    state["persist"] = True
    operation = str(uuid4())
    source = b"Synthetic DOCX original"
    monkeypatch.setattr(owner, "importar_docx", lambda *args, **kwargs: checkpoint.content)
    document = service.importar_legado(processo_id=state["head"]["processo_id"], tipo="dfd", operation_id=operation,
                                      formato="docx", original_docx=source)
    monkeypatch.setattr(owner, "importar_docx", lambda *args, **kwargs: pytest.fail("committed import must not reconvert"))
    retried = service.importar_legado(processo_id=document.processo_id, tipo="dfd", operation_id=operation,
                                    formato="docx", original_docx=source)
    assert retried.payload == document.payload
    assert state["server_calls"][0] == state["server_calls"][1]
    with pytest.raises(owner.ConflitoDocumento):
        service.importar_legado(processo_id=document.processo_id, tipo="dfd", operation_id=operation,
                                formato="docx", original_docx=b"different")
