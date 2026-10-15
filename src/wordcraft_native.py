"""Validate a checkpoint with the pinned native engine; never authorizes or saves.

The server supplies the Node path, bundle and trusted manifest hash. They must
never be taken from browser events. Document bytes travel only through stdin.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import re
import subprocess

from .wordcraft_protocol import MAX_BYTES

WORKER = Path(__file__).resolve().parents[1] / "assets/wordcraft_editor/validate.mjs"
MAX_EXPORT_BYTES = 64 * 1024 * 1024


class ModeloRecusado(ValueError):
    pass


class MotorIndisponivel(RuntimeError):
    pass


def _closed_object(pairs):
    result = dict(pairs)
    if len(result) != len(pairs):
        raise ValueError("Duplicate IPC fields")
    return result


def _invoke(content: bytes, *, node: Path, bundle: Path, manifest_sha256: str, extra=()):
    if not isinstance(content, bytes) or not content or len(content) > MAX_BYTES:
        raise ModeloRecusado("Checkpoint vazio ou excessivo.")
    if not isinstance(manifest_sha256, str) or not re.fullmatch(r"[0-9a-f]{64}", manifest_sha256):
        raise MotorIndisponivel("Manifesto pinado obrigatório.")
    if not node.is_absolute() or not node.is_file() or not bundle.is_absolute() or not bundle.is_dir():
        raise MotorIndisponivel("Runtime e bundle locais explícitos obrigatórios.")
    # Child receives no Supabase/provider keys, tokens, user environment or NODE_OPTIONS.
    environment = {name: os.environ[name] for name in ("SystemRoot", "WINDIR", "TEMP", "TMP") if name in os.environ}
    try:
        result = subprocess.run([str(node), str(WORKER), "--bundle", str(bundle),
                                 "--manifest-sha256", manifest_sha256, *extra],
                                input=content, capture_output=True, timeout=30,
                                env=environment, cwd=bundle, check=False)
    except (OSError, subprocess.TimeoutExpired):
        raise MotorIndisponivel("Não foi possível concluir a validação nativa.") from None
    return result


def _validation_response(result):
    if len(result.stdout) > 1024:
        raise MotorIndisponivel("Resposta nativa excede o contrato.")
    try:
        response = json.loads(result.stdout, object_pairs_hook=_closed_object)
    except (ValueError, UnicodeDecodeError):
        raise MotorIndisponivel("Resposta nativa inválida.") from None
    if (result.returncode == 0 and isinstance(response, dict) and response.keys() == {"valid"}
            and response["valid"] is True):
        return
    if (result.returncode == 2 and isinstance(response, dict) and response.keys() == {"valid", "code"}
            and response["valid"] is False and response["code"] == "MODEL_REJECTED"):
        raise ModeloRecusado("O motor recusou o modelo do checkpoint.")
    raise MotorIndisponivel("O motor não confirmou a validade do checkpoint.")


def validar(content: bytes, *, node: Path, bundle: Path, manifest_sha256: str) -> None:
    _validation_response(_invoke(content, node=node, bundle=bundle, manifest_sha256=manifest_sha256))


def exportar(content: bytes, *, formato: str, node: Path, bundle: Path, manifest_sha256: str) -> bytes:
    if formato not in {"docx", "pdf"}:
        raise ModeloRecusado("Formato de exportação não autorizado.")
    result = _invoke(content, node=node, bundle=bundle, manifest_sha256=manifest_sha256,
                     extra=("--export-format", formato))
    if result.returncode != 0:
        _validation_response(result)
    output = result.stdout
    signature = b"%PDF-" if formato == "pdf" else b"PK\x03\x04"
    if (not isinstance(output, bytes) or not 0 < len(output) <= MAX_EXPORT_BYTES
            or not output.startswith(signature)):
        raise MotorIndisponivel("O motor não confirmou o artefato solicitado.")
    return output
