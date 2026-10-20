"""Admissão fail-closed do runtime WordCraft operacional.

O artefato interno de QA é deliberadamente recusado. A configuração vem só do
servidor e nunca de query params, sessão do browser ou payload do componente.
"""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path
import re
from urllib.parse import urlsplit

from . import db

FLAG = "wordcraft_editor"
STATUS_OPERACIONAL = "GOVCONNECT_WORDCRAFT_DEPLOY_APPROVED"
MAX_MANIFEST = 1024 * 1024
MAX_ASSET = 80 * 1024 * 1024
MAX_TOTAL = 200 * 1024 * 1024
STATIC_ROOT = Path(__file__).resolve().parents[1] / "static"


class ErroRuntime(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class Runtime:
    node: Path
    bundle: Path
    manifest_sha256: str
    origin: str
    module_url: str
    wasm_url: str
    upstream_commit: str
    producer_commit: str


def ativo() -> bool:
    return db.flag_ativa(FLAG)


def _env(nome: str) -> str:
    valor = os.environ.get(nome, "")
    if not valor:
        raise ErroRuntime("Configuração operacional do WordCraft incompleta.")
    return valor


def _nome(valor) -> str:
    if (not isinstance(valor, str) or not re.fullmatch(r"[A-Za-z0-9._/-]+", valor)
            or valor.startswith("/") or any(p in {"", ".", ".."} for p in valor.split("/"))):
        raise ErroRuntime("Inventário operacional contém caminho inválido.")
    return valor


def carregar() -> Runtime:
    """Valida integralmente manifesto e assets antes de devolver URLs públicas."""
    node = Path(_env("GOVDOCS_WORDCRAFT_NODE"))
    bundle = Path(_env("GOVDOCS_WORDCRAFT_BUNDLE"))
    expected = _env("GOVDOCS_WORDCRAFT_MANIFEST_SHA256")
    origin = _env("GOVDOCS_WORDCRAFT_ORIGIN")
    parsed = urlsplit(origin)
    if (not node.is_absolute() or not node.is_file() or not bundle.is_absolute()
            or not bundle.is_dir() or bundle.name != "wordcraft"
            or bundle.parent.resolve() != STATIC_ROOT.resolve()):
        raise ErroRuntime("Runtime ou namespace estático operacional inválido.")
    if (parsed.scheme not in {"http", "https"} or not parsed.netloc or parsed.username
            or parsed.password or origin != f"{parsed.scheme}://{parsed.netloc}"):
        raise ErroRuntime("Origem pública operacional inválida.")
    if not re.fullmatch(r"[0-9a-f]{64}", expected):
        raise ErroRuntime("Hash de manifesto operacional inválido.")
    manifest_path = bundle / "qa-manifest.json"
    try:
        if manifest_path.stat().st_size > MAX_MANIFEST:
            raise ErroRuntime("Manifesto operacional excessivo.")
        raw = manifest_path.read_bytes()
        if hashlib.sha256(raw).hexdigest() != expected:
            raise ErroRuntime("Manifesto operacional divergiu do pin.")
        manifest = json.loads(raw)
    except ErroRuntime:
        raise
    except Exception:
        raise ErroRuntime("Manifesto operacional indisponível ou inválido.") from None
    try:
        # O release preserva docs/ junto ao código para que o pin auditado não
        # seja substituído por configuração de ambiente.
        lock = json.loads((Path(__file__).resolve().parents[1] /
                           "docs/wordcraft/upstream.lock.json").read_text(encoding="utf-8"))
    except Exception:
        raise ErroRuntime("Pin upstream do release indisponível.") from None
    upstream = manifest.get("upstream_commit")
    producer = manifest.get("govconnect_commit")
    items = manifest.get("files")
    if (manifest.get("status") != STATUS_OPERACIONAL or upstream != lock.get("commit")
            or not re.fullmatch(r"[0-9a-f]{40}", str(producer or ""))
            or not isinstance(items, list) or not 2 <= len(items) <= 100):
        raise ErroRuntime("Artefato não foi aprovado para o runtime operacional.")
    seen, total, entries = set(), 0, {}
    root = bundle.resolve()
    for item in items:
        try:
            name = _nome(item["path"])
            size, digest = item["bytes"], item["sha256"]
        except (KeyError, TypeError):
            raise ErroRuntime("Inventário operacional inválido.") from None
        if (name in seen or type(size) is not int or not 0 < size <= MAX_ASSET
                or not re.fullmatch(r"[0-9a-f]{64}", str(digest))):
            raise ErroRuntime("Asset operacional ambíguo ou excessivo.")
        seen.add(name)
        total += size
        if total > MAX_TOTAL:
            raise ErroRuntime("Runtime operacional excede o orçamento de assets.")
        try:
            path = (bundle / name).resolve(strict=True)
            data = path.read_bytes()
        except OSError:
            raise ErroRuntime("Asset operacional ausente.") from None
        if (not path.is_relative_to(root) or not path.is_file() or len(data) != size
                or hashlib.sha256(data).hexdigest() != digest):
            raise ErroRuntime("Asset operacional divergiu do manifesto.")
        if path.suffix == ".wasm" and not data.startswith(b"\0asm\x01\0\0\0"):
            raise ErroRuntime("Asset WASM operacional inválido.")
        if "/" not in name and path.suffix in {".js", ".wasm"}:
            if path.suffix in entries:
                raise ErroRuntime("Entradas JS/WASM operacionais ambíguas.")
            entries[path.suffix] = "/app/static/wordcraft/" + name
    if set(entries) != {".js", ".wasm"}:
        raise ErroRuntime("Entradas JS/WASM operacionais ausentes.")
    notice_path = bundle / "notices/manifest.json"
    try:
        if notice_path.stat().st_size > MAX_MANIFEST:
            raise ValueError()
        notices = json.loads(notice_path.read_bytes())
        notice_items = notices["files"]
    except Exception:
        raise ErroRuntime("Manifesto de avisos do release inválido.") from None
    if (notices.get("status") != "UPSTREAM_AND_FONT_NOTICES_VERIFIED"
            or notices.get("upstream_commit") != upstream
            or not isinstance(notice_items, list) or len(notice_items) != 13):
        raise ErroRuntime("Avisos e licenças do release não foram comprovados.")
    public = {"qa-manifest.json", "notices/manifest.json", *seen}
    for item in notice_items:
        try:
            relative = _nome(item["path"])
            digest = item["sha256_canonical_lf"]
            path = (bundle / "notices" / relative).resolve(strict=True)
            data = path.read_bytes()
        except Exception:
            raise ErroRuntime("Aviso obrigatório ausente ou inválido.") from None
        if (not path.is_relative_to(root / "notices") or len(data) > 200_000
                or b"\0" in data or hashlib.sha256(data).hexdigest() != digest):
            raise ErroRuntime("Aviso obrigatório divergiu do manifesto.")
        try:
            data.decode("utf-8")
        except UnicodeDecodeError:
            raise ErroRuntime("Aviso obrigatório não é UTF-8.") from None
        public.add("notices/" + relative)
    actual = {path.relative_to(root).as_posix() for path in root.rglob("*") if path.is_file()}
    if actual != public:
        raise ErroRuntime("Namespace público contém arquivo não inventariado.")
    return Runtime(node.resolve(), root, expected, origin, entries[".js"],
                   entries[".wasm"], upstream, producer)
