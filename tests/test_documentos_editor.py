"""Owner contract tests with transport/native stubs; real engine/RLS are separate."""
from dataclasses import replace
import hashlib
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import pytest

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
    def eq(self, *args): return self
    def limit(self, *args): return self


@pytest.fixture
def setup(monkeypatch):
    payload = b"opaque unit fixture, not a native document"
    identity = {"sub": str(uuid4()), "role": "authenticated", "app_metadata": {"tenant_id": str(uuid4())}}
    head = dict(id=str(uuid4()), processo_id=str(uuid4()), tipo="dfd", revision=1,
                content_hash=hashlib.sha256(payload).hexdigest(), status="rascunho")
    checkpoint = Checkpoint(str(uuid4()), 1, head["content_hash"], payload)
    state = {"context": identity, "server_calls": [], "native_calls": [], "head": head}
    row = dict(payload="\\x" + payload.hex(), content_hash=head["content_hash"],
               editor_schema_version=owner.SCHEMA, wordcraft_commit=owner.UPSTREAM)
    state["row"] = row

    class User:
        def rpc(self, name, params):
            assert name == "documento_editor_contexto" and params == {}
            return Query(state["context"])

        def table(self, name):
            return Query([state["head"]] if name == "documentos_editor" else [state["row"]])

    class Server:
        def rpc(self, name, params):
            assert name == "documento_editor_checkpoint"
            state["server_calls"].append(params)
            result = dict(document_id=params["p_document"], revision=params["p_expected_revision"] + 1,
                          content_hash=params["p_content_hash"], operation_id=params["p_operation"], replayed=False)
            return Query(state.get("server_result", [result]))

    monkeypatch.setattr(owner.db, "cliente_do_usuario", lambda: User())
    monkeypatch.setattr(owner.db, "_cliente", lambda: Server())
    monkeypatch.setattr(owner, "validar", lambda value, **kwargs: state["native_calls"].append(value))
    service = owner.DocumentoService(node=Path("C:/server/node.exe"), bundle=Path("C:/server/bundle"), manifest_sha256="a" * 64)
    return service, state, checkpoint


def test_commit_uses_verified_context_and_returns_only_correlated_receipt(setup):
    service, state, checkpoint = setup
    receipt = service.checkpoint(state["head"]["id"], checkpoint)
    assert receipt.revision == 2 and receipt.request_id == checkpoint.request_id
    assert state["server_calls"][0]["p_claims"] is state["context"]
    assert state["server_calls"][0]["p_process"] == state["head"]["processo_id"]
    assert state["native_calls"] == [checkpoint.content]
    assert "payload" not in repr(receipt)


def test_open_rechecks_native_bytes_and_hash(setup):
    service, state, checkpoint = setup
    document = service.abrir(state["head"]["id"])
    assert document.payload == checkpoint.content and document.revision == 1
    assert checkpoint.content.decode() not in repr(document)
    assert state["native_calls"] == [checkpoint.content]


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
    assert artifact.content_hash == hashlib.sha256(artifact.payload).hexdigest()
    assert "synthetic artifact" not in repr(artifact)


def test_stale_export_does_not_execute_the_exporter(setup, monkeypatch):
    service, state, checkpoint = setup
    monkeypatch.setattr(owner, "exportar", lambda *args, **kwargs: pytest.fail("stale revision"))
    with pytest.raises(owner.ConflitoDocumento):
        service.exportar(state["head"]["id"], expected_revision=2,
                         content_hash=checkpoint.content_hash, formato="pdf")
