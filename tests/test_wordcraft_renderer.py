import hashlib
from uuid import uuid4

import pytest

from src.ui import wordcraft_editor as editor
from src.wordcraft_protocol import ErroPonte, Ponte


@pytest.fixture
def bridge():
    return Ponte("http://127.0.0.1:8771", str(uuid4()), str(uuid4()), str(uuid4()),
                 "a" * 64, content_hash=hashlib.sha256(b"fixture").hexdigest())


def test_rerun_preserva_chave_callback_e_bytes_autorizados(bridge, monkeypatch):
    calls = []
    monkeypatch.setattr(editor, "_renderer", lambda: lambda **kwargs: calls.append(kwargs))
    callback = lambda: None
    for _ in range(2):
        editor.render_editor(bridge, b"fixture", module_url="/app/static/wordcraft/editor.js",
                             wasm_url="/app/static/wordcraft/editor.wasm", on_edit_change=callback)
    assert calls[0]["key"] == calls[1]["key"] == f"wordcraft_{bridge.instance_id}"
    assert calls[0]["on_edit_change"] is callback
    assert calls[0]["height"] == calls[1]["height"] == 800
    assert calls[0]["width"] == calls[1]["width"] == "stretch"
    assert calls[0]["data"]["checkpoint_base64"] == "Zml4dHVyZQ=="
    assert "ack" not in calls[0]["data"]


@pytest.mark.parametrize("asset", ["https://external.invalid/a.js", "//external.invalid/a.js",
    "/app/static/wordcraft/../editor.js", "/app/static/wordcraft/%2e%2e/a.js",
    "/app/static/wordcraft/editor.js?token=value", "/app/static/wordcraft//editor.js",
    "/app/static/wordcraft/\\..\\editor.js", "/app/static/wordcraft/ed\nitor.js"])
def test_asset_fora_do_caminho_nao_monta(bridge, asset):
    with pytest.raises(ErroPonte):
        editor.opening_data(bridge, b"fixture", module_url=asset, wasm_url="/app/static/wordcraft/a.wasm")


def test_hash_divergente_e_callback_ausente_nao_montam(bridge, monkeypatch):
    monkeypatch.setattr(editor, "_renderer", lambda: pytest.fail("must reject before mount"))
    arguments = dict(module_url="/app/static/wordcraft/a.js", wasm_url="/app/static/wordcraft/a.wasm")
    with pytest.raises(ErroPonte):
        editor.opening_data(bridge, b"changed", **arguments)
    with pytest.raises(TypeError):
        editor.render_editor(bridge, b"fixture", on_edit_change=None, **arguments)


def test_renderer_so_emite_ack_aceito_pela_ponte_apos_commit(bridge, monkeypatch):
    calls = []
    monkeypatch.setattr(editor, "_renderer", lambda: lambda **kwargs: calls.append(kwargs))
    arguments = dict(module_url="/app/static/wordcraft/a.js", wasm_url="/app/static/wordcraft/a.wasm",
                     on_edit_change=lambda: None)
    for kind, payload in [("loaded", {"content_hash": bridge.content_hash}), ("changed", {}),
            ("checkpoint", {"schema_version": "gc-wordcraft-snapshot/v1", "content_hash": bridge.content_hash,
                             "content_base64": "Zml4dHVyZQ=="})]:
        envelope = {key: getattr(bridge, key) for key in ("instance_id", "session_id", "document_id", "nonce")}
        envelope.update(protocol="gc-wordcraft/v1", sequence=bridge.sequence + 1, expected_revision=bridge.revision,
                        request_id=str(uuid4()), event="document." + kind, payload=payload)
        checkpoint = bridge.receber(envelope, origin=bridge.origin, source_ok=True)
    editor.render_editor(bridge, b"fixture", **arguments)
    assert "ack" not in calls[-1]["data"]
    bridge.falhar_checkpoint(request_id=checkpoint.request_id)
    editor.render_editor(bridge, b"fixture", **arguments)
    assert calls[-1]["data"]["save_error"] == {"request_id": checkpoint.request_id, "conflict": False}
    assert "ack" not in calls[-1]["data"]
    bridge.repetir_checkpoint()
    bridge.confirmar_checkpoint(request_id=checkpoint.request_id, revision=1, content_hash=checkpoint.content_hash)
    editor.render_editor(bridge, b"fixture", **arguments)
    assert "save_error" not in calls[-1]["data"]
    assert calls[-1]["data"]["ack"] == {"request_id": checkpoint.request_id, "revision": 1,
                                        "content_hash": checkpoint.content_hash}
    copy = bridge.ack_persistido(); copy["revision"] = 99
    assert bridge.ack_persistido()["revision"] == 1
