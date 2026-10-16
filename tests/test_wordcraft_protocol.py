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


def test_canvas_requires_a_requested_correlated_freeze_before_release(ponte):
    abrir(ponte)
    command = str(uuid4())
    assert ponte.canvas_bloqueado() is None
    with pytest.raises(ErroPonte):
        receber(ponte, evento(ponte, "frozen", dict(command_id=command, content_hash=DIGEST, generation="1")))
    ponte.solicitar_bloqueio(command)
    outbound = ponte.controle_pendente()
    outbound["content_hash"] = "a" * 64
    assert ponte.controle_pendente()["content_hash"] == DIGEST
    receber(ponte, evento(ponte, "frozen", dict(command_id=command, content_hash=DIGEST, generation="1")))
    proof = ponte.canvas_bloqueado()
    assert ponte.state == "frozen" and proof["command_id"] == command and proof["revision"] == 0
    proof["revision"] = 99
    assert ponte.canvas_bloqueado()["revision"] == 0
    for kind in ("changed", "checkpoint"):
        with pytest.raises(ErroPonte):
            receber(ponte, evento(ponte, kind))
    with pytest.raises(ErroPonte): ponte.liberar_bloqueio(str(uuid4()))
    ponte.liberar_bloqueio(command)
    assert ponte.controle_pendente()["action"] == "release"
    assert ponte.canvas_bloqueado() is None  # Ineligible before the browser can unlock.
    receber(ponte, evento(ponte, "released", {"command_id": command}))
    assert ponte.state == "saved" and ponte.canvas_bloqueado() is None and ponte.controle_pendente() is None
    with pytest.raises(ErroPonte): ponte.solicitar_bloqueio(command)


@pytest.mark.parametrize("case", ["command", "hash", "generation", "extra", "dirty", "unrequested_release"])
def test_forged_canvas_proof_does_not_consume_state(ponte, case):
    abrir(ponte)
    command = str(uuid4())
    ponte.solicitar_bloqueio(command)
    payload = dict(command_id=command, content_hash=DIGEST, generation="12")
    if case == "command": payload["command_id"] = str(uuid4())
    if case == "hash": payload["content_hash"] = "a" * 64
    if case == "generation": payload["generation"] = "1e20"
    if case == "extra": payload["approved"] = True
    if case == "dirty": receber(ponte, evento(ponte, "changed"))
    value = evento(ponte, "released", {"command_id": command}) if case == "unrequested_release" else evento(ponte, "frozen", payload)
    before = deepcopy(ponte.__dict__)
    with pytest.raises(ErroPonte): receber(ponte, value)
    assert ponte.__dict__ == before and ponte.canvas_bloqueado() is None


def test_late_dirty_notice_cancels_freeze_and_requires_a_new_command(ponte):
    abrir(ponte)
    command = str(uuid4())
    ponte.solicitar_bloqueio(command)
    changed = evento(ponte, "changed")
    failed = evento(ponte, "control_failed", dict(command_id=command, reason="dirty"))
    failed["sequence"] += 1
    ponte.receber_lote({"events": [changed, failed]}, origin=ponte.origin, source_ok=True)
    assert ponte.state == "dirty" and ponte.canvas_bloqueado() is None and ponte.controle_pendente() is None
    assert ponte.falha_controle() == {"command_id": command, "reason": "dirty"}
    pending = checkpoint(ponte)
    ponte.confirmar_checkpoint(request_id=pending.request_id, revision=1, content_hash=DIGEST)
    with pytest.raises(ErroPonte): ponte.solicitar_bloqueio(command)
    ponte.solicitar_bloqueio(str(uuid4()))
    assert ponte.controle_pendente()["revision"] == 1 and ponte.falha_controle() is None


@pytest.mark.parametrize("reason", [None, [], {}, "approved", "timeout"])
def test_control_failure_has_a_closed_reason_vocabulary(ponte, reason):
    abrir(ponte)
    command = str(uuid4()); ponte.solicitar_bloqueio(command)
    before = deepcopy(ponte.__dict__)
    with pytest.raises(ErroPonte):
        receber(ponte, evento(ponte, "control_failed", dict(command_id=command, reason=reason)))
    assert ponte.__dict__ == before


def checkpoint(p):
    return receber(p, evento(p, "checkpoint", {
        "content_hash": DIGEST, "content_base64": base64.b64encode(CONTENT).decode(),
        "schema_version": "gc-wordcraft-snapshot/v1"}))


def sujo(p):
    abrir(p)
    receber(p, evento(p, "changed"))


def lote(p):
    loaded = evento(p, "loaded", {"content_hash": DIGEST})
    changed = evento(p, "changed"); changed["sequence"] = 2
    cp = evento(p, "checkpoint", {"content_hash": DIGEST,
        "content_base64": base64.b64encode(CONTENT).decode(), "schema_version": "gc-wordcraft-snapshot/v1"})
    cp["sequence"] = 3
    during = evento(p, "changed"); during["sequence"] = 4
    return {"events": [loaded, changed, cp, during]}


def test_lote_coalescido_preserva_checkpoint_e_edicao_durante_save(ponte):
    batch = lote(ponte)
    cp = ponte.receber_lote(batch, origin=ponte.origin, source_ok=True)
    assert cp.content == CONTENT and ponte.sequence == 4
    assert ponte.receber_lote(batch, origin=ponte.origin, source_ok=True) is None
    ponte.confirmar_checkpoint(request_id=cp.request_id, revision=1, content_hash=DIGEST)
    assert ponte.state == "dirty"
    # A rerun may still carry the consumed old-revision prefix after its persisted ACK.
    assert ponte.receber_lote(batch, origin=ponte.origin, source_ok=True) is None
    assert ponte.state == "dirty" and ponte.revision == 1


def test_changed_emitted_during_save_can_arrive_after_the_persisted_ack(ponte):
    sujo(ponte)
    pending = checkpoint(ponte)
    delayed = evento(ponte, "changed")  # Emitted with the pre-ACK revision.
    ponte.confirmar_checkpoint(request_id=pending.request_id, revision=1, content_hash=DIGEST)
    assert receber(ponte, delayed) is None
    assert ponte.state == "dirty" and ponte.revision == 1 and ponte.content_hash == DIGEST
    assert checkpoint(ponte).expected_revision == 1


def test_late_dirty_notice_does_not_allow_an_old_checkpoint(ponte):
    sujo(ponte)
    pending = checkpoint(ponte)
    delayed = evento(ponte, "changed")
    ponte.confirmar_checkpoint(request_id=pending.request_id, revision=1, content_hash=DIGEST)
    receber(ponte, delayed)
    stale = evento(ponte, "checkpoint", {"content_hash": DIGEST,
        "content_base64": base64.b64encode(CONTENT).decode(), "schema_version": "gc-wordcraft-snapshot/v1"})
    stale["expected_revision"] = 0
    with pytest.raises(ErroPonte, match="Revisão"):
        receber(ponte, stale)
    assert ponte.state == "dirty" and ponte.revision == 1


def test_old_changed_without_a_local_persisted_ack_is_rejected(ponte):
    abrir(ponte)
    ponte.revision = 1  # Reopened persisted state, not a local ACK of this instance.
    old = evento(ponte, "changed"); old["expected_revision"] = 0
    with pytest.raises(ErroPonte, match="Revisão"):
        receber(ponte, old)


@pytest.mark.parametrize("case", ["gap", "order", "bad_hash", "scope", "origin"])
def test_lote_invalido_e_atomico(ponte, case):
    batch = lote(ponte)
    if case == "gap": batch["events"].pop(1)
    if case == "order": batch["events"].reverse()
    if case == "bad_hash": batch["events"][2]["payload"]["content_hash"] = "0" * 64
    if case == "scope": batch["events"][-1]["document_id"] = str(uuid4())
    before = deepcopy(ponte)
    with pytest.raises(ErroPonte):
        ponte.receber_lote(batch, origin="https://attacker.invalid" if case == "origin" else ponte.origin, source_ok=True)
    assert ponte == before


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
