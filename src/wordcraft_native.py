"""Validate a checkpoint with the pinned native engine; never authorizes or saves.

The server supplies the Node path, bundle and trusted manifest hash. They must
never be taken from browser events. Document bytes travel only through stdin.
"""
from __future__ import annotations

import json
import io
import os
from pathlib import Path
import posixpath
import re
import stat
import struct
import subprocess
import zlib
from urllib.parse import urlsplit
from xml.etree import ElementTree
from zipfile import BadZipFile, ZIP_DEFLATED, ZIP_STORED, ZipFile

from .wordcraft_protocol import MAX_BYTES

WORKER = Path(__file__).resolve().parents[1] / "assets/wordcraft_editor/validate.mjs"
MAX_EXPORT_BYTES = 64 * 1024 * 1024
MAX_DOCX_PARTS = 1024
MAX_DOCX_PART_BYTES = 8 * 1024 * 1024
MAX_DOCX_EXPANDED_BYTES = 32 * 1024 * 1024
_REL_NS = "http://schemas.openxmlformats.org/package/2006/relationships"
_CONTENT_NS = "http://schemas.openxmlformats.org/package/2006/content-types"
_WORD_NS = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
_REL_BASE = "http://schemas.openxmlformats.org/officeDocument/2006/relationships/"
_REL_TYPES = frozenset(_REL_BASE + name for name in (
    "officeDocument", "extended-properties", "custom-properties", "styles", "settings",
    "webSettings", "fontTable", "theme", "numbering", "header", "footer", "footnotes",
    "endnotes", "comments", "image", "hyperlink", "customXml", "customXmlProps")) | frozenset({
        _REL_NS + "/metadata/core-properties", _REL_NS + "/metadata/thumbnail",
        "http://schemas.microsoft.com/office/2007/relationships/stylesWithEffects",
        "http://schemas.microsoft.com/office/2011/relationships/commentsExtended"})
_DOCX_PART = re.compile(
    r"(?:\[Content_Types\]\.xml|_rels/\.rels|docProps/(?:core|app|custom)\.xml|"
    r"docProps/thumbnail\.(?:png|jpe?g)|word/(?:document|styles|stylesWithEffects|settings|"
    r"webSettings|fontTable|numbering|footnotes|endnotes|comments|commentsExtended)\.xml|"
    r"word/(?:header|footer)[0-9]+\.xml|word/theme/theme[0-9]+\.xml|"
    r"word/media/[A-Za-z0-9_.-]+\.(?:png|jpe?g|gif|bmp|tiff?)|"
    r"word/_rels/[A-Za-z0-9_.-]+\.xml\.rels|customXml/item(?:Props)?[0-9]+\.xml|"
    r"customXml/_rels/item[0-9]+\.xml\.rels)\Z")


class ModeloRecusado(ValueError):
    pass


class MotorIndisponivel(RuntimeError):
    pass


def _closed_object(pairs):
    result = dict(pairs)
    if len(result) != len(pairs):
        raise ValueError("Duplicate IPC fields")
    return result


def _docx_xml(data: bytes):
    # UTF-8 only keeps the DTD check unambiguous (UTF-16 can hide ASCII with NULs).
    text = data.decode("utf-8-sig")
    if "<!doctype" in text.lower() or "<!entity" in text.lower() or "\x00" in text:
        raise ValueError("Unsafe XML declaration")
    root = ElementTree.fromstring(text)
    stack = [(root, 0)]
    nodes = 0
    while stack:
        element, depth = stack.pop()
        nodes += 1
        if depth > 64 or nodes > 250_000:
            raise ValueError("XML structure exceeds import bound")
        if element.tag.rsplit("}", 1)[-1] in {"altChunk", "object", "OLEObject", "control", "attachedTemplate"}:
            raise ValueError("Unsupported active or opaque object")
        stack.extend((child, depth + 1) for child in element)
    # Never carry fields that can load files, execute DDE or hide executable links
    # into an exported DOCX. Concatenation catches split instrText commands.
    fragments = [element.text or "" for element in root.iter(f"{{{_WORD_NS}}}instrText")]
    fragments += [element.get(f"{{{_WORD_NS}}}instr", "") for element in root.iter(f"{{{_WORD_NS}}}fldSimple")]
    instructions = " ".join(fragments) + " " + "".join(fragments)
    field_commands = re.sub("HYPERLINK", "", instructions, flags=re.I)
    if re.search(r"DDE|INCLUDETEXT|INCLUDEPICTURE|LINK|MACROBUTTON", field_commands, re.I):
        raise ValueError("External or executable field")
    if re.search(r"(?:file|javascript|data|vbscript):|\\\\", instructions, re.I):
        raise ValueError("Unsafe field target")
    return root


def _docx_part_bytes(content: bytes, part) -> bytes:
    # ZipExtFile truncates reads at the declared expanded size. Check the actual
    # deflate stream as well, so forged small metadata cannot hide a larger bomb
    # from admission control before the independent Rust ZIP reader sees it.
    header = struct.unpack_from("<4s5H3I2H", content, part.header_offset)
    if (header[0] != b"PK\x03\x04" or header[2] != part.flag_bits
            or header[3] != part.compress_type or header[1] > 20):
        raise ValueError("Inconsistent ZIP local header")
    expected = (part.CRC, part.compress_size, part.file_size)
    if (not part.flag_bits & 8 and header[6:9] != expected
            or part.flag_bits & 8 and any(local not in {0, central} for local, central in zip(header[6:9], expected))):
        raise ValueError("ZIP local sizes or CRC differ")
    name_start = part.header_offset + 30
    data_start = name_start + header[9] + header[10]
    data_end = data_start + part.compress_size
    if data_start > len(content) or data_end > len(content):
        raise ValueError("ZIP compressed data escaped the package")
    raw_name = content[name_start:name_start + header[9]]
    if raw_name.decode("utf-8" if part.flag_bits & (1 << 11) else "cp437") != part.filename:
        raise ValueError("ZIP local and central names differ")
    compressed = content[data_start:data_end]
    if part.compress_type == ZIP_STORED:
        data = compressed
    else:
        decoder = zlib.decompressobj(-15)
        data = decoder.decompress(compressed, part.file_size + 1)
        if not decoder.eof or decoder.unconsumed_tail or decoder.unused_data:
            raise ValueError("Deflate stream exceeds or contradicts ZIP metadata")
    if len(data) != part.file_size or zlib.crc32(data) != part.CRC:
        raise ValueError("Actual ZIP size or CRC differs")
    return data


def _check_docx_relationships(name: str, root, names: set[str]) -> None:
    if root.tag != f"{{{_REL_NS}}}Relationships":
        raise ValueError("Invalid relationships root")
    if name == "_rels/.rels":
        base = ""
    else:
        directory, filename = name.rsplit("/_rels/", 1)
        if directory + "/" + filename.removesuffix(".rels") not in names:
            raise ValueError("Relationships have no owning part")
        base = directory
    ids = set()
    office_docs = 0
    for relationship in root:
        if (relationship.tag != f"{{{_REL_NS}}}Relationship"
                or not {"Id", "Type", "Target"} <= relationship.attrib.keys()
                or not relationship.attrib.keys() <= {"Id", "Type", "Target", "TargetMode"}):
            raise ValueError("Unexpected relationship schema")
        identity, kind, target = (relationship.get(key, "") for key in ("Id", "Type", "Target"))
        if not identity or identity in ids or kind not in _REL_TYPES or not target or len(target) > 2048:
            raise ValueError("Unexpected relationship")
        ids.add(identity)
        mode = relationship.get("TargetMode", "Internal")
        if mode == "External":
            uri = urlsplit(target)
            if (kind != _REL_BASE + "hyperlink" or uri.scheme.lower() not in {"https", "http", "mailto"}
                    or (uri.scheme.lower() in {"http", "https"} and (not uri.hostname or uri.username or uri.password))
                    or "\\" in target or any(ord(char) < 32 for char in target)):
                raise ValueError("External relationship is not an inert hyperlink")
        elif mode == "Internal":
            if any(char in target for char in ("\\", ":", "%", "?", "#")) or target.startswith("/"):
                raise ValueError("Invalid internal relationship")
            resolved = posixpath.normpath(posixpath.join(base, target))
            if resolved.startswith("../") or resolved not in names:
                raise ValueError("Missing or escaped relationship target")
            if name == "_rels/.rels" and kind == _REL_BASE + "officeDocument":
                if resolved != "word/document.xml":
                    raise ValueError("Unexpected document root")
                office_docs += 1
        else:
            raise ValueError("Unknown relationship target mode")
    if name == "_rels/.rels" and office_docs != 1:
        raise ValueError("Package must have exactly one DOCX document")


def preflight_docx(content: bytes) -> None:
    """Closed ZIP/OPC upload policy, before starting Node or parsing with WASM.

    No extraction or network access. This is admission control, not another
    document importer; only the pinned WordCraft engine interprets the document.
    """
    try:
        if (not isinstance(content, bytes) or not 0 < len(content) <= MAX_BYTES
                or not content.startswith(b"PK\x03\x04")):
            raise ValueError("Invalid DOCX byte bound or signature")
        with ZipFile(io.BytesIO(content)) as archive:
            parts = archive.infolist()
            if not 3 <= len(parts) <= MAX_DOCX_PARTS:
                raise ValueError("Unexpected DOCX part count")
            names, folded = set(), set()
            total = 0
            for part in parts:
                name = part.filename
                total += part.file_size
                if (part.orig_filename != name or not _DOCX_PART.fullmatch(name) or len(name) > 240
                        or name in names or name.casefold() in folded or part.is_dir()
                        or any(segment in {"", ".", ".."} for segment in name.split("/"))
                        or stat.S_ISLNK(part.external_attr >> 16)
                        or part.flag_bits & ((1 << 0) | (1 << 6) | (1 << 13))
                        or part.compress_type not in {ZIP_STORED, ZIP_DEFLATED}
                        or part.extract_version > 20 or part.header_offset < 0
                        or not 0 <= part.file_size <= MAX_DOCX_PART_BYTES
                        or total > MAX_DOCX_EXPANDED_BYTES):
                    raise ValueError("Unsupported or excessive DOCX part")
                names.add(name)
                folded.add(name.casefold())
            if not {"[Content_Types].xml", "_rels/.rels", "word/document.xml"} <= names:
                raise ValueError("Missing required DOCX parts")
            roots = {}
            for part in parts:
                # ZipFile also checks local-name consistency and overlapping
                # entries. A bounded deflate check then verifies actual expansion.
                with archive.open(part) as stream:
                    if len(stream.read(part.file_size + 1)) != part.file_size:
                        raise ValueError("Actual DOCX part size differs")
                data = _docx_part_bytes(content, part)
                if len(data) != part.file_size:
                    raise ValueError("Actual DOCX part size differs")
                if part.filename.endswith((".xml", ".rels")):
                    roots[part.filename] = _docx_xml(data)
            types = roots["[Content_Types].xml"]
            if types.tag != f"{{{_CONTENT_NS}}}Types":
                raise ValueError("Invalid content types root")
            overrides, defaults = {}, {}
            for item in types:
                if item.tag == f"{{{_CONTENT_NS}}}Override" and item.attrib.keys() == {"PartName", "ContentType"}:
                    key = item.get("PartName", "")
                    if not key.startswith("/") or key[1:] not in names or key in overrides:
                        raise ValueError("Invalid content type override")
                    overrides[key] = item.get("ContentType", "")
                elif item.tag == f"{{{_CONTENT_NS}}}Default" and item.attrib.keys() == {"Extension", "ContentType"}:
                    key = item.get("Extension", "")
                    if key in defaults or not re.fullmatch(r"[a-zA-Z0-9]+", key):
                        raise ValueError("Invalid content type default")
                    defaults[key] = item.get("ContentType", "")
                else:
                    raise ValueError("Unexpected content type schema")
                kind = item.get("ContentType", "").lower()
                if not kind or any(token in kind for token in ("macro", "vba", "activex", "oleobject", "external")):
                    raise ValueError("Unsupported content type")
            if overrides.get("/word/document.xml") != "application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml":
                raise ValueError("Package is not a DOCX document")
            if roots["word/document.xml"].tag != f"{{{_WORD_NS}}}document":
                raise ValueError("Invalid DOCX document root")
            for name in names - {"[Content_Types].xml"}:
                if "/" + name not in overrides and name.rsplit(".", 1)[-1] not in defaults:
                    raise ValueError("Part has no declared content type")
            for name, root in roots.items():
                if name.endswith(".rels"):
                    _check_docx_relationships(name, root, names)
    except (BadZipFile, ElementTree.ParseError, UnicodeError, ValueError, OSError, RuntimeError,
            EOFError, NotImplementedError, zlib.error, struct.error):
        raise ModeloRecusado("DOCX recusado pelo preflight de importação; preserve o original para compatibilidade.") from None


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


def importar_docx(content: bytes, *, node: Path, bundle: Path, manifest_sha256: str) -> bytes:
    """Import bytes with the pinned engine; returns a checkpoint, never persists it."""
    preflight_docx(content)
    result = _invoke(content, node=node, bundle=bundle, manifest_sha256=manifest_sha256,
                     extra=("--import-format", "docx"))
    if result.returncode != 0:
        _validation_response(result)
    output = result.stdout
    if not isinstance(output, bytes) or not 0 < len(output) <= MAX_BYTES:
        raise MotorIndisponivel("O motor não confirmou o checkpoint importado.")
    try:
        value = json.loads(output, object_pairs_hook=_closed_object)
        if (not isinstance(value, dict) or value.keys() != {"schema", "document", "media", "passthrough"}
                or value["schema"] != "gc-wordcraft-snapshot/v1"
                or not isinstance(value["document"], dict) or not isinstance(value["document"].get("body"), list)
                or not isinstance(value["media"], dict) or not isinstance(value["passthrough"], dict)):
            raise ValueError("Unexpected imported checkpoint")
    except (ValueError, UnicodeError, RecursionError):
        raise MotorIndisponivel("Resposta de importação nativa inválida.") from None
    return output
