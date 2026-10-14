"""Mount the experimental document-scoped host; the caller owns ACL and persistence.

This module is deliberately not mounted by steps/revisao until the real G1 slice
passes. A component state callback must consume batches through Ponte and only
return a persisted ACK after the canonical backend commits the checkpoint.
"""
from __future__ import annotations

import base64
from functools import lru_cache
import hashlib
from pathlib import Path
from urllib.parse import urlsplit

from ..wordcraft_protocol import MAX_BYTES, Ponte, ErroPonte


def _asset(value: str, origin: str, extension: str) -> str:
    if not isinstance(value, str):
        raise ErroPonte("Asset do editor inválido.")
    parsed = urlsplit(value)
    if (value != parsed.path or "\\" in value or not value.isascii()
            or parsed.scheme or parsed.netloc or parsed.query or parsed.fragment
            or not parsed.path.startswith("/app/static/wordcraft/")
            or not parsed.path.endswith(extension) or "%" in parsed.path
            or any(part in {".", "..", ""} for part in parsed.path.split("/")[1:])):
        raise ErroPonte("Asset do editor fora do caminho autorizado.")
    return origin + parsed.path


def opening_data(bridge: Ponte, checkpoint: bytes, *, module_url: str, wasm_url: str) -> dict:
    """Build data from a server-owned bridge and authorized bytes, never browser IDs."""
    if (not isinstance(checkpoint, bytes) or not checkpoint or len(checkpoint) > MAX_BYTES
            or hashlib.sha256(checkpoint).hexdigest() != bridge.content_hash):
        raise ErroPonte("Bytes de abertura divergem da revisão autorizada.")
    return {"instance_id": bridge.instance_id, "session_id": bridge.session_id,
            "document_id": bridge.document_id, "nonce": bridge.nonce,
            "revision": bridge.revision, "content_hash": bridge.content_hash,
            "checkpoint_base64": base64.b64encode(checkpoint).decode("ascii"),
            "module_url": _asset(module_url, bridge.origin, ".js"),
            "wasm_url": _asset(wasm_url, bridge.origin, ".wasm"),
            "event_ack": bridge.sequence}


@lru_cache(maxsize=1)
def _renderer():
    import streamlit as st
    host = Path(__file__).resolve().parents[2] / "assets/wordcraft_editor/host.mjs"
    return st.components.v2.component(
        "govconnect_wordcraft_editor", html='<section class="gc-wordcraft-editor"></section>',
        js=host.read_text(encoding="utf-8"), isolate_styles=True)


def render_editor(bridge: Ponte, checkpoint: bytes, *, module_url: str, wasm_url: str,
                  on_edit_change):
    """Mount with a stable key. This function never synthesizes a save confirmation.

    The owner of the callback validates the model, authorization, CAS and operation
    identity before calling bridge.confirmar_checkpoint. A persisted ACK is read
    only from that bridge, never an independent renderer argument. Opening bytes remain the backend's
    latest persisted revision; draft bytes live in the native editor until ACK.
    """
    if not callable(on_edit_change):
        raise TypeError("Callback backend obrigatório.")
    data = opening_data(bridge, checkpoint, module_url=module_url, wasm_url=wasm_url)
    persisted_ack = bridge.ack_persistido()
    if persisted_ack is not None:
        data["ack"] = persisted_ack
    save_error = bridge.falha_pendente()
    if save_error is not None:
        data["save_error"] = save_error
    return _renderer()(data=data, key=f"wordcraft_{bridge.instance_id}",
                       height="content", width="stretch", on_edit_change=on_edit_change)
