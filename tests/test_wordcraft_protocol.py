"""Provas offline de contrato; não simulam build WASM nem RLS como aprovados."""
import base64
import hashlib
from copy import deepcopy
from uuid import uuid4

import pytest

from src.wordcraft_protocol import ErroPonte, Ponte, PROTOCOL

CONTENT = b'{"synthetic": "contract fixture, not native WordCraft corpus"}'
DIGEST = hashlib.sha256(CONTENT).hexdigest()


@pytest.fixture
def ponte():
    return Ponte("http://127.0.0.1:8771", str(uuid4()), str(uuid4()),
                 str(uuid4()), "a" * 64, content_hash=DIGEST)


def evento(p, kind, payload=None):
    return dict(protocol=PROTOCOL, request_id=str(uuid4()), instance_id=p.instance_id,
                session_id=p.session_id, document_id=p.document_id,
                nonce=p.nonce, expected_revision=p.revision,
                sequence=p.sequence + 1, event=f"document.{kind}", payload=payload or {})


def receber(p, e, **kw):
    return p.receber(e, origin=kw.get("origin", p.origin),
                     source_ok=kw.get("source_ok", True))


def abrir(p):
    receber(p, evento(p, "loaded", {"content_hash": DIGEST}))


def checkpoint(p):
    return receber(p, evento(p, "checkpoint", {
        "content_hash": DIGEST, "content_base64": base64.b64encode(CONTENT).decode(),
        "schema_version": "gc-wordcraft-snapshot/v1"}))


def sujo(p):
    abrir(p)
    receber(p, evento(p, "changed"))


def test_ack_so_apos_persistencia_e_reabertura(ponte):
    sujo(ponte)
    cp = checkpoint(ponte)
    assert ponte.state == "saving" and ponte.revision == 0
    ponte.confirmar_checkpoint(request_id=cp.request_id, revision=1, content_hash=DIGEST)
    assert ponte.state == "saved" and ponte.revision == 1
    assert cp.content == CONTENT
    nova = Ponte(ponte.origin, str(uuid4()), str(uuid4()), ponte.document_id,
                 "b" * 64, revision=1, content_hash=DIGEST)
    abrir(nova)
    assert nova.state == "ready" and nova.revision == 1


@pytest.mark.parametrize("key,value", [
    ("protocol", "bad"), ("nonce", "x" * 64), ("document_id", str(uuid4())),
    ("session_id", str(uuid4())), ("instance_id", str(uuid4())),
    ("expected_revision", 9), ("expected_revision", False),
    ("sequence", True), ("sequence", -1), ("sequence", 2**53),
    ("request_id", "not-uuid"), ("event", "document.saved"),
    ("event", "command"), ("event", "file.open"), ("tenant_id", "other"),
    ("role", "admin"), ("payload", {"tenant_id": "other"}),
])
def test_schema_fechado_e_escopo_nao_consumem_evento(ponte, key, value):
    e = evento(ponte, "loaded", {"content_hash": DIGEST})
    before = deepcopy(ponte)
    e[key] = value
    with pytest.raises(ErroPonte):
        receber(ponte, e)
    assert ponte == before


@pytest.mark.parametrize("kw", [{"origin": "https://attacker.invalid"},
                                 {"source_ok": False}, {"source_ok": 1}])
def test_janela_origem(ponte, kw):
    with pytest.raises(ErroPonte):
        receber(ponte, evento(ponte, "loaded", {"content_hash": DIGEST}), **kw)
    assert ponte.state == "opening"


def test_replay_e_ordem(ponte):
    e = evento(ponte, "loaded", {"content_hash": DIGEST})
    receber(ponte, e)
    with pytest.raises(ErroPonte):
        receber(ponte, e)
    other = evento(ponte, "changed")
    other["sequence"] = 1
    with pytest.raises(ErroPonte):
        receber(ponte, other)


@pytest.mark.parametrize("field,value", [
    ("content_hash", "0" * 64), ("content_hash", "invalid"),
    ("content_base64", "%%%"), ("content_base64", ""),
    ("schema_version", "markdown"), ("path", "C:/private"),
])
def test_bytes_limitados_e_integridade(ponte, field, value):
    sujo(ponte)
    payload = {"content_hash": DIGEST,
               "content_base64": base64.b64encode(CONTENT).decode(),
               "schema_version": "gc-wordcraft-snapshot/v1"}
    payload[field] = value
    with pytest.raises(ErroPonte):
        receber(ponte, evento(ponte, "checkpoint", payload))
    assert ponte.state == "dirty" and ponte.revision == 0


def test_limite_payload_antes_de_decodificar(ponte, monkeypatch):
    from src import wordcraft_protocol as mod
    sujo(ponte)
    monkeypatch.setattr(mod, "MAX_BYTES", 1)
    with pytest.raises(ErroPonte):
        checkpoint(ponte)
    assert ponte.state == "dirty"


def test_retry_preserva_id_e_bytes_sem_ack_falso(ponte):
    sujo(ponte)
    cp = checkpoint(ponte)
    ponte.falhar_checkpoint(request_id=cp.request_id)
    assert ponte.state == "error" and ponte.revision == 0
    receber(ponte, evento(ponte, "changed"))
    assert ponte.state == "error"
    assert ponte.repetir_checkpoint() is cp
    ponte.confirmar_checkpoint(request_id=cp.request_id, revision=1, content_hash=DIGEST)
    assert ponte.state == "dirty"


def test_retry_tipado_preserva_edicoes_novas_e_identidade_original(ponte):
    sujo(ponte)
    cp = checkpoint(ponte)
    ponte.falhar_checkpoint(request_id=cp.request_id)
    receber(ponte, evento(ponte, "changed"))
    retry = evento(ponte, "retry", {"request_id": cp.request_id})
    assert receber(ponte, retry) is cp
    assert ponte.state == "saving"
    with pytest.raises(ErroPonte):
        receber(ponte, retry)
    ponte.confirmar_checkpoint(request_id=cp.request_id, revision=1, content_hash=DIGEST)
    assert ponte.state == "dirty"


def test_retry_de_outro_request_nao_consumido(ponte):
    sujo(ponte)
    cp = checkpoint(ponte)
    ponte.falhar_checkpoint(request_id=cp.request_id)
    with pytest.raises(ErroPonte):
        receber(ponte, evento(ponte, "retry", {"request_id": str(uuid4())}))
    assert ponte.state == "error"


def test_alteracao_durante_gravacao_continua_suja(ponte):
    sujo(ponte)
    cp = checkpoint(ponte)
    receber(ponte, evento(ponte, "changed"))
    ponte.confirmar_checkpoint(request_id=cp.request_id, revision=1, content_hash=DIGEST)
    assert ponte.state == "dirty"


def test_conflito_nao_permite_retry_ou_overwrite(ponte):
    sujo(ponte)
    cp = checkpoint(ponte)
    ponte.falhar_checkpoint(request_id=cp.request_id, conflict=True)
    with pytest.raises(ErroPonte):
        ponte.repetir_checkpoint()
    with pytest.raises(ErroPonte):
        receber(ponte, evento(ponte, "changed"))
    assert ponte.state == "conflict" and ponte.revision == 0
    with pytest.raises(ErroPonte):
        ponte.confirmar_checkpoint(request_id=cp.request_id, revision=1, content_hash=DIGEST)


@pytest.mark.parametrize("value", [None, [], {}, True, 1.2, "á" * 64])
@pytest.mark.parametrize("key", ["event", "nonce", "sequence", "request_id"])
def test_entrada_hostil_falha_fechada(ponte, value, key):
    e = evento(ponte, "loaded", {"content_hash": DIGEST})
    e[key] = value
    with pytest.raises(ErroPonte):
        receber(ponte, e)
    assert ponte.state == "opening"


@pytest.mark.parametrize("args", [
    {"request_id": str(uuid4()), "revision": 1, "content_hash": DIGEST},
    {"revision": 0}, {"revision": 2}, {"revision": True},
    {"content_hash": "0" * 64},
])
def test_ack_incorreto_preserva_pendente(ponte, args):
    sujo(ponte)
    cp = checkpoint(ponte)
    params = dict(request_id=cp.request_id, revision=1, content_hash=DIGEST)
    params.update(args)
    with pytest.raises(ErroPonte):
        ponte.confirmar_checkpoint(**params)
    assert ponte.state == "saving" and ponte.revision == 0


@pytest.mark.parametrize("origin", ["*", "null", "https://example.org/path",
                                     "https://a:b@example.org", "https://example.org/"])
def test_configuracao_origem_explicita(ponte, origin):
    with pytest.raises(ErroPonte):
        Ponte(origin, ponte.instance_id, ponte.session_id, ponte.document_id,
              ponte.nonce, content_hash=DIGEST)
