"""Revision-bound anchors derived from native-validated checkpoint bytes.

This is a read-only projection, never an alternate document/patch engine. The
backend must own the index, native configuration and transition verifier. A
browser or an AI-supplied selection cannot establish block identity or ACL.
"""
from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
import re
from typing import Callable
from uuid import UUID, uuid5

from .blocos import hash_texto
from . import achados, perfis, validacao
from .wordcraft_native import validar
from .wordcraft_protocol import CHECKPOINT_SCHEMA, MAX_BYTES, _hash, _inteiro, _uuid

INDEX_SCHEMA = "gc-wordcraft-block-index/v1"
MAX_BLOCOS = 20_000
MAX_DEPTH = 32
MAX_INDEX_BYTES = 8 * 1024 * 1024
PART_KINDS = frozenset({"header", "footer", "footnote", "endnote", "comment", "textBox"})


class ErroAncora(ValueError):
    """The index or its preconditions cannot identify an exact native target."""


@dataclass(frozen=True)
class CaminhoNativo:
    parte: int | None  # None = StoryRef::Body; integer = StoryRef::Part(u32).
    indices: tuple[int, ...]

    def posicao(self) -> dict:
        """A fresh native StoryRef/Path projection, without offsets or commands."""
        return {"story": "body" if self.parte is None else {"part": self.parte},
                "path": list(self.indices)}


@dataclass(frozen=True)
class BlocoNativo:
    block_id: str
    caminho: CaminhoNativo
    story_kind: str
    tipo: str
    content_hash: str


@dataclass(frozen=True)
class Invalidacao:
    block_id: str
    motivo: str  # No claim about whether a user deleted, replaced or moved text.


@dataclass(frozen=True)
class IndiceNativo:
    document_id: str
    revision: int
    content_hash: str
    engine_manifest_sha256: str
    blocos: tuple[BlocoNativo, ...]
    areas_nao_enderecaveis: tuple[str, ...] = ()
    invalidacoes: tuple[Invalidacao, ...] = ()
    schema: str = INDEX_SCHEMA


def desserializar_indice(content: bytes) -> IndiceNativo:
    """Decode a bounded closed sidecar; native validation is still mandatory."""
    try:
        if not isinstance(content, bytes) or not 0 < len(content) <= MAX_INDEX_BYTES:
            raise ValueError()
        root = json.loads(content, object_pairs_hook=_objeto_fechado, parse_constant=_constante_invalida)
        if (not isinstance(root, dict) or root.keys() != {"schema", "document_id", "revision", "content_hash",
                "engine_manifest_sha256", "blocos", "areas_nao_enderecaveis", "invalidacoes"}
                or root["schema"] != INDEX_SCHEMA):
            raise ValueError()
        _metadata(root["document_id"], root["revision"], root["content_hash"], root["engine_manifest_sha256"])
        blocks, invalidations = [], []
        if not isinstance(root["blocos"], list) or len(root["blocos"]) > MAX_BLOCOS:
            raise ValueError()
        for item in root["blocos"]:
            if not isinstance(item, dict) or item.keys() != {"block_id", "parte", "indices", "story_kind", "tipo", "content_hash"}:
                raise ValueError()
            _uuid(item["block_id"])
            _hash(item["content_hash"])
            if not isinstance(item["indices"], list):
                raise ValueError()
            path = CaminhoNativo(item["parte"], tuple(item["indices"]))
            _caminho(path)
            if (item["tipo"] not in {"para", "table"} or item["story_kind"] not in PART_KINDS | {"body"}
                    or (path.parte is None) != (item["story_kind"] == "body")):
                raise ValueError()
            blocks.append(BlocoNativo(item["block_id"], path, item["story_kind"], item["tipo"], item["content_hash"]))
        if not isinstance(root["invalidacoes"], list) or len(root["invalidacoes"]) > MAX_BLOCOS:
            raise ValueError()
        for item in root["invalidacoes"]:
            if not isinstance(item, dict) or item.keys() != {"block_id", "motivo"}:
                raise ValueError()
            _uuid(item["block_id"])
            if item["motivo"] not in {"ambigua", "sem_correspondencia", "build_alterado"}:
                raise ValueError()
            invalidations.append(Invalidacao(item["block_id"], item["motivo"]))
        uncovered = root["areas_nao_enderecaveis"]
        if (not isinstance(uncovered, list) or len(uncovered) > MAX_BLOCOS
                or any(not isinstance(s, str) or not 0 < len(s) <= 200 for s in uncovered)
                or len(set(uncovered)) != len(uncovered)
                or len({b.block_id for b in blocks}) != len(blocks)
                or len({b.caminho for b in blocks}) != len(blocks)
                or len({b.block_id for b in invalidations}) != len(invalidations)
                or {b.block_id for b in blocks} & {b.block_id for b in invalidations}):
            raise ValueError()
        return IndiceNativo(root["document_id"], root["revision"], root["content_hash"],
            root["engine_manifest_sha256"], tuple(blocks), tuple(uncovered), tuple(invalidations))
    except (ValueError, KeyError, TypeError, UnicodeError, RecursionError, OverflowError):
        raise ErroAncora("Índice serializado inválido.") from None


def serializar_indice(indice: IndiceNativo) -> bytes:
    """Canonical bytes for hashing/storage, never a second document source."""
    if not isinstance(indice, IndiceNativo):
        raise ErroAncora("Índice não reconhecido.")
    value = {"schema": indice.schema, "document_id": indice.document_id, "revision": indice.revision,
        "content_hash": indice.content_hash, "engine_manifest_sha256": indice.engine_manifest_sha256,
        "blocos": [{"block_id": b.block_id, "parte": b.caminho.parte, "indices": list(b.caminho.indices),
            "story_kind": b.story_kind, "tipo": b.tipo, "content_hash": b.content_hash} for b in indice.blocos],
        "areas_nao_enderecaveis": list(indice.areas_nao_enderecaveis),
        "invalidacoes": [{"block_id": b.block_id, "motivo": b.motivo} for b in indice.invalidacoes]}
    encoded = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")
    desserializar_indice(encoded)
    return encoded


@dataclass(frozen=True)
class VinculoOperacional:
    """Candidate linkage; only a trusted backend verifier can confirm it.

    Hashes and paths are checked here, but do not themselves prove a native
    editing operation. Never populate the verifier from browser input.
    """
    block_id: str
    origem: CaminhoNativo
    destino: CaminhoNativo
    source_hash: str
    target_hash: str


@dataclass(frozen=True)
class TransicaoNativa:
    document_id: str
    source_revision: int
    source_hash: str
    target_revision: int
    target_hash: str
    engine_manifest_sha256: str


ConfirmadorVinculos = Callable[[TransicaoNativa, tuple[VinculoOperacional, ...]], bool]


def _metadata(document_id: str, revision: int, content_hash: str, manifest_hash: str) -> None:
    try:
        _uuid(document_id)
        _inteiro(revision, minimum=1)
        _hash(content_hash)
        _hash(manifest_hash)
    except ValueError:
        raise ErroAncora("Documento, revisão ou hash inválido para o índice.") from None


def _caminho(caminho: CaminhoNativo) -> None:
    if (not isinstance(caminho, CaminhoNativo)
            or (caminho.parte is not None and
                (type(caminho.parte) is not int or not 0 <= caminho.parte <= 2**32 - 1))
            or not isinstance(caminho.indices, tuple)
            or not 1 <= len(caminho.indices) <= 1 + 3 * MAX_DEPTH
            or len(caminho.indices) % 3 != 1
            or any(type(n) is not int or not 0 <= n <= 2**32 - 1 for n in caminho.indices)):
        raise ErroAncora("Caminho nativo inválido.")


def _objeto_fechado(pairs):
    value = dict(pairs)
    if len(value) != len(pairs):
        raise ErroAncora("Checkpoint com campos duplicados.")
    return value


def _constante_invalida(_):
    raise ErroAncora("Checkpoint não contém JSON finito.")


def _fingerprint(value: dict) -> str:
    # Reuses the canonical application's text hash; never re-encodes a checkpoint.
    return hash_texto(json.dumps(value, ensure_ascii=False, sort_keys=True,
                                 separators=(",", ":"), allow_nan=False))


def _projetar(content: bytes, *, content_hash: str, node: Path, bundle: Path,
              manifest_sha256: str) -> tuple[tuple[tuple, ...], tuple[str, ...]]:
    if (not isinstance(content, bytes) or not 0 < len(content) <= MAX_BYTES
            or hashlib.sha256(content).hexdigest() != content_hash):
        raise ErroAncora("Bytes não correspondem ao checkpoint declarado.")
    # The native engine remains the model authority. No plain JSON fallback.
    validar(content, node=node, bundle=bundle, manifest_sha256=manifest_sha256)
    try:
        root = json.loads(content, object_pairs_hook=_objeto_fechado,
                          parse_constant=_constante_invalida)
        if (not isinstance(root, dict) or root.keys() != {"schema", "document", "media", "passthrough"}
                or root["schema"] != CHECKPOINT_SCHEMA or not isinstance(root["document"], dict)):
            raise ErroAncora("Container nativo não reconhecido.")
        document = root["document"]
        entries = []

        def walk(blocks, part, story_kind, prefix=()):
            if not isinstance(blocks, list) or len(prefix) > 3 * MAX_DEPTH:
                raise ErroAncora("Estrutura de blocos excede o contrato de projeção.")
            for index, block in enumerate(blocks):
                if len(entries) >= MAX_BLOCOS or not isinstance(block, dict):
                    raise ErroAncora("Quantidade ou estrutura de blocos inválida.")
                kind = block.get("kind")
                if kind not in {"para", "table"}:
                    raise ErroAncora("Tipo nativo sem adaptador de âncora.")
                path = CaminhoNativo(part, (*prefix, index))
                _caminho(path)
                entries.append((path, story_kind, kind, _fingerprint(block)))
                if kind == "table":
                    for row_index, row in enumerate(block["rows"]):
                        for cell_index, cell in enumerate(row["cells"]):
                            walk(cell["blocks"], part, story_kind,
                                 (*path.indices, row_index, cell_index))

        walk(document["body"], None, "body")
        parts = document["parts"]
        if not isinstance(parts, dict):
            raise ErroAncora("Stories nativas inválidas.")
        for key, part in sorted(parts.items(), key=lambda item: int(item[0])):
            part_id = int(key)
            if str(part_id) != key or not 0 <= part_id <= 2**32 - 1 or part["kind"] not in PART_KINDS:
                raise ErroAncora("Story nativa sem adaptador de âncora.")
            walk(part["blocks"], part_id, part["kind"])
        uncovered = []
        # These are real native blocks, but have no StoryRef/Path address. Expose
        # the limitation instead of silently treating this as a complete index.
        for group in ("footnoteSeparators", "endnoteSeparators"):
            separators = document.get(group, {})
            if not isinstance(separators, dict):
                raise ErroAncora("Separadores nativos inválidos.")
            for key, value in separators.items():
                if value is not None:
                    uncovered.append(f"{group}.{key}")
        return tuple(entries), tuple(sorted(uncovered))
    except ErroAncora:
        raise
    except (KeyError, TypeError, ValueError, UnicodeError, RecursionError, OverflowError):
        raise ErroAncora("Não foi possível projetar o checkpoint validado.") from None


def _novo_id(document_id, revision, content_hash, manifest_sha256, entry):
    path, story, kind, digest = entry
    name = json.dumps([INDEX_SCHEMA, revision, content_hash, manifest_sha256, path.parte,
                       path.indices, story, kind, digest], separators=(",", ":"))
    return str(uuid5(UUID(document_id), name))


def construir_indice(content: bytes, *, document_id: str, revision: int,
                     content_hash: str, node: Path, bundle: Path,
                     manifest_sha256: str) -> IndiceNativo:
    """Initial/retry index from exact bytes approved by the pinned engine."""
    _metadata(document_id, revision, content_hash, manifest_sha256)
    entries, uncovered = _projetar(content, content_hash=content_hash, node=node,
                                   bundle=bundle, manifest_sha256=manifest_sha256)
    blocks = tuple(BlocoNativo(_novo_id(document_id, revision, content_hash, manifest_sha256, entry), *entry)
                   for entry in entries)
    return IndiceNativo(document_id, revision, content_hash, manifest_sha256, blocks, uncovered)


def validar_indice(indice: IndiceNativo, content: bytes, *, node: Path, bundle: Path,
                   manifest_sha256: str) -> None:
    """Revalidate a server-owned stored index against its original checkpoint."""
    if not isinstance(indice, IndiceNativo) or indice.schema != INDEX_SCHEMA:
        raise ErroAncora("Índice não reconhecido.")
    _metadata(indice.document_id, indice.revision, indice.content_hash, manifest_sha256)
    if indice.engine_manifest_sha256 != manifest_sha256:
        raise ErroAncora("O build nativo mudou; reconstrução controlada obrigatória.")
    entries, uncovered = _projetar(content, content_hash=indice.content_hash, node=node,
                                   bundle=bundle, manifest_sha256=manifest_sha256)
    if (not isinstance(indice.blocos, tuple) or len(indice.blocos) != len(entries)
            or indice.areas_nao_enderecaveis != uncovered):
        raise ErroAncora("Índice não cobre a projeção exata da revisão.")
    ids = set()
    for block, entry in zip(indice.blocos, entries):
        if not isinstance(block, BlocoNativo):
            raise ErroAncora("Bloco do índice inválido.")
        try:
            _uuid(block.block_id)
        except ValueError:
            raise ErroAncora("Identidade de bloco inválida.") from None
        if (block.block_id in ids or
                (block.caminho, block.story_kind, block.tipo, block.content_hash) != entry):
            raise ErroAncora("Índice não corresponde aos blocos da revisão.")
        ids.add(block.block_id)


def _signature(block):
    return block.caminho.parte, block.story_kind, block.tipo, block.content_hash


def reconciliar_indice(anterior: IndiceNativo, content_anterior: bytes, content: bytes, *,
                      revision: int, content_hash: str, node: Path, bundle: Path,
                      manifest_sha256: str, vinculos: tuple[VinculoOperacional, ...] = (),
                      confirmar_vinculos: ConfirmadorVinculos | None = None) -> IndiceNativo:
    """Preserve unique exact-content identity, or explicitly verified lineage.

    No positional/similarity inference is used for edited or duplicate blocks.
    New/ambiguous blocks get new IDs; all lost IDs are explicitly invalidated.
    This function never executes an edit or authorizes use of an old proposal.
    """
    validar_indice(anterior, content_anterior, node=node, bundle=bundle,
                   manifest_sha256=manifest_sha256)
    _metadata(anterior.document_id, revision, content_hash, manifest_sha256)
    if revision != anterior.revision + 1:
        raise ErroAncora("A reconciliação exige revisões consecutivas.")
    current = construir_indice(content, document_id=anterior.document_id, revision=revision,
                              content_hash=content_hash, node=node, bundle=bundle,
                              manifest_sha256=manifest_sha256)
    before = {block.block_id: block for block in anterior.blocos}
    after = {block.caminho: block for block in current.blocos}
    assigned = {}
    used_ids = set()
    if not isinstance(vinculos, tuple) or len(vinculos) > MAX_BLOCOS:
        raise ErroAncora("Vínculos operacionais inválidos.")
    for link in vinculos:
        if not isinstance(link, VinculoOperacional):
            raise ErroAncora("Vínculo operacional não reconhecido.")
        _caminho(link.origem)
        _caminho(link.destino)
        old = before.get(link.block_id)
        new = after.get(link.destino)
        if (old is None or new is None or old.caminho != link.origem
                or old.content_hash != link.source_hash or new.content_hash != link.target_hash
                or old.tipo != new.tipo or old.story_kind != new.story_kind
                or old.caminho.parte != new.caminho.parte
                or link.destino in assigned or link.block_id in used_ids):
            raise ErroAncora("Vínculo não corresponde a uma relação única entre as revisões.")
        assigned[link.destino] = link.block_id
        used_ids.add(link.block_id)
    if vinculos:
        transition = TransicaoNativa(anterior.document_id, anterior.revision, anterior.content_hash,
                                    revision, content_hash, manifest_sha256)
        try:
            confirmed = callable(confirmar_vinculos) and confirmar_vinculos(transition, vinculos) is True
        except Exception:
            # An unavailable receipt service is not permission to guess identity.
            raise ErroAncora("Não foi possível confirmar o vínculo operacional no backend.") from None
        if not confirmed:
            raise ErroAncora("O backend não confirmou a operação que preserva a identidade.")
    counts_before = Counter(_signature(block) for block in anterior.blocos)
    counts_after = Counter(_signature(block) for block in current.blocos)
    unique = {_signature(block): block for block in anterior.blocos
              if counts_before[_signature(block)] == 1}
    blocks = []
    for block in current.blocos:
        identifier = assigned.get(block.caminho)
        candidate = unique.get(_signature(block))
        if (identifier is None and candidate is not None
                and counts_after[_signature(block)] == 1 and candidate.block_id not in used_ids):
            identifier = candidate.block_id
            used_ids.add(identifier)
        blocks.append(BlocoNativo(identifier or block.block_id, block.caminho, block.story_kind,
                                  block.tipo, block.content_hash))
    invalid = tuple(Invalidacao(block.block_id,
                               "ambigua" if counts_before[_signature(block)] > 1 or
                               counts_after[_signature(block)] > 1 else "sem_correspondencia")
                    for block in anterior.blocos if block.block_id not in used_ids)
    return IndiceNativo(current.document_id, revision, content_hash, manifest_sha256,
                        tuple(blocks), current.areas_nao_enderecaveis, invalid)


def resolver_ancora(indice: IndiceNativo, block_id: str, *, document_id: str, revision: int,
                   content_hash: str, block_hash: str) -> CaminhoNativo:
    """Resolve a server-owned index only with exact current preconditions.

    Callers still authorize scope/ACL and execute through the existing canonical
    patch engine. A resulting path is valid only for this revision/checkpoint.
    """
    if (not isinstance(indice, IndiceNativo) or indice.schema != INDEX_SCHEMA
            or not isinstance(indice.blocos, tuple) or len(indice.blocos) > MAX_BLOCOS
            or any(not isinstance(block, BlocoNativo) for block in indice.blocos)):
        raise ErroAncora("Índice não reconhecido.")
    _metadata(document_id, revision, content_hash, indice.engine_manifest_sha256)
    try:
        _uuid(block_id)
        _hash(block_hash)
    except ValueError:
        raise ErroAncora("Precondição de bloco inválida.") from None
    if (indice.document_id != document_id or indice.revision != revision
            or indice.content_hash != content_hash):
        raise ErroAncora("Âncora de revisão diferente; gere uma nova proposta.")
    matches = [block for block in indice.blocos if block.block_id == block_id]
    if len(matches) != 1 or matches[0].content_hash != block_hash:
        raise ErroAncora("Âncora ausente, ambígua ou com hash divergente.")
    _caminho(matches[0].caminho)
    return matches[0].caminho


# Read-only adapter for the existing audit/patch policy. These are paragraph
# views, including paragraphs inside native cells, never a Markdown source.
CLAUSE_STYLES = frozenset({"GovDocsClausula", "Heading1", "Heading2", "Heading3"})
INSTITUTIONAL_STYLES = frozenset({"GovDocsTitulo", "GovDocsNota", "Header", "Footer"})


def _titulo_estrutural(text: str, objects: object, *, heading: bool,
                       top_level: bool) -> str | None:
    """Read a bookmarked clause title without making its paragraph editable.

    WordCraft represents the start/end of a DOCX bookmark as U+FFFC around the
    visible paragraph text.  Only that exact boundary form is structural.  An
    inline marker, an unpaired marker, or a marker outside a top-level typed
    heading remains an opaque object and therefore outside complete coverage.
    """
    if "\ufffc" not in text:
        return text if not objects else None
    if (not heading or not top_level or not text.startswith("\ufffc")
            or not text.endswith("\ufffc")):
        return None
    visible = text[1:-1]
    if not visible or "\ufffc" in visible:
        return None
    if (not isinstance(objects, list) or len(objects) != 2
            or not isinstance(objects[0], dict) or not isinstance(objects[1], dict)
            or set(objects[0]) != {"type", "name"}
            or set(objects[1]) != {"type", "name"}
            or objects[0]["type"] != "bookmarkStart"
            or objects[1]["type"] != "bookmarkEnd"
            or objects[0]["name"] != objects[1]["name"]
            or not isinstance(objects[0]["name"], str)
            or re.fullmatch(r"[A-Za-z][A-Za-z0-9_]{0,63}", objects[0]["name"]) is None):
        return None
    return visible


@dataclass(frozen=True)
class DocumentoNativo:
    checkpoint: bytes
    indice: IndiceNativo


@dataclass(frozen=True)
class BlocoGovernado:
    path: str
    tipo: str
    clausula: int | None
    conteudo: str
    hash: str
    ancora: BlocoNativo
    bloqueio: str | None

    def canonico(self) -> dict:
        return {"path": self.path, "tipo": self.tipo, "clausula": self.clausula,
                "conteudo": self.conteudo, "hash": self.hash}


@dataclass(frozen=True)
class ProjecaoNativa:
    documento: str
    document_id: str
    revision: int
    content_hash: str
    engine_manifest_sha256: str
    blocos: tuple[BlocoGovernado, ...]
    texto_analise: str
    areas_nao_cobertas: tuple[str, ...]
    impedimentos_autocorrecao: tuple[str, ...]

    @property
    def apto_analise(self) -> bool:
        return not self.areas_nao_cobertas

    @property
    def apto_autocorrecao(self) -> bool:
        return self.apto_analise and not self.impedimentos_autocorrecao

    def snapshot_documento(self) -> dict:
        return {"documento": self.documento, "hash": self.content_hash,
                "blocos": [block.canonico() for block in self.blocos]}

    def vinculo(self) -> dict:
        return {"documentId": self.document_id, "revision": self.revision,
                "sourceHash": self.content_hash,
                "engineManifestSha256": self.engine_manifest_sha256}


def _modelo_validado(content: bytes) -> dict:
    """Read only; callers must first validate bytes/index with the native API."""
    return json.loads(content, object_pairs_hook=_objeto_fechado,
                      parse_constant=_constante_invalida)


def _bloco_modelo(root: dict, caminho: CaminhoNativo) -> dict:
    blocks = (root["document"]["body"] if caminho.parte is None else
              root["document"]["parts"][str(caminho.parte)]["blocks"])
    block = blocks[caminho.indices[0]]
    for offset in range(1, len(caminho.indices), 3):
        row, cell, child = caminho.indices[offset:offset + 3]
        block = block["rows"][row]["cells"][cell]["blocks"][child]
    return block


def _texto_inline(text: str) -> bool:
    # Matches the native command's explicit prohibition of controls/separators.
    return (isinstance(text, str) and not any(ord(c) < 32 or 127 <= ord(c) <= 159
            or c in "\u2028\u2029\ufffc" for c in text))


def _paragrafo_uniforme(block: dict) -> bool:
    text, runs = block.get("text"), block.get("runs")
    paragraph_props, mark = block.get("props", {}), block.get("mark", {})
    if (not isinstance(text, str) or not text or not _texto_inline(text)
            or block.get("objects") or not isinstance(runs, list) or not runs
            or any(paragraph_props.get(k) is not None for k in ("fmtChange", "numChange"))
            or any(mark.get(k) is not None for k in ("ins", "del", "fmtChange"))):
        return False
    props = runs[0].get("props", {})
    if not isinstance(props, dict) or any(props.get(k) is not None for k in ("ins", "del", "fmtChange")):
        return False
    data, end = text.encode("utf-8"), 0
    try:
        for run in runs:
            size = run.get("len")
            if type(size) is not int or size <= 0 or run.get("props", {}) != props:
                return False
            end += size
            data[:end].decode("utf-8", errors="strict")
        return end == len(data)
    except (UnicodeError, AttributeError):
        return False


def projetar_documento(doc_key: str, content: bytes, *, indice: IndiceNativo,
                       node: Path, bundle: Path, manifest_sha256: str) -> ProjecaoNativa:
    """Governed analysis view from exact native bytes and a backend-owned index.

    A complete textual view is distinct from eligibility for automatic editing.
    Unknown object text/auxiliary regions fail coverage explicitly.
    """
    if not isinstance(doc_key, str) or re.fullmatch(r"[a-z][a-z0-9_]{0,63}", doc_key) is None:
        raise ErroAncora("Chave de documento inválida para projeção.")
    validar_indice(indice, content, node=node, bundle=bundle, manifest_sha256=manifest_sha256)
    root = _modelo_validado(content)
    result, gaps, impediments = [], list(indice.areas_nao_enderecaveis), []
    clause, section, occurrences = None, "preambulo", Counter()
    signature_section = False
    settings = root["document"].get("settings", {})
    if settings.get("trackChanges") or settings.get("protection") is not None:
        impediments.append("documento_protegido_ou_tracking")
    for anchor in indice.blocos:
        if anchor.tipo != "para":
            continue  # Table geometry remains in the native model/index.
        block = _bloco_modelo(root, anchor.caminho)
        text, style = block["text"], block.get("props", {}).get("style")
        if not isinstance(text, str):
            raise ErroAncora("Parágrafo sem texto reconhecível na projeção.")
        body = anchor.story_kind == "body"
        top_level = body and len(anchor.caminho.indices) == 1
        heading = style in CLAUSE_STYLES
        structural_text = _titulo_estrutural(text, block.get("objects", []),
                                             heading=heading, top_level=top_level)
        if structural_text is None:
            gaps.append(f"objeto:{anchor.block_id}")
        visible_text = structural_text if structural_text is not None else text
        match = validacao._RE_CLAUSULA.fullmatch("## " + visible_text) if heading else None
        if top_level and match:
            clause = int(match.group(1))
            occurrences[clause] += 1
            suffix = str(clause) if occurrences[clause] == 1 else f"{clause}.{occurrences[clause]}"
            section = f"clausula/{suffix}"
            signature_section = False
            if occurrences[clause] > 1:
                impediments.append("numeracao_ambigua")
        elif top_level and heading:
            # Do not let an unnumbered heading silently inherit FIXED policy.
            clause, section = None, "preambulo"
            signature_section = False
        elif top_level and (validacao._RE_CLAUSULA.fullmatch(visible_text)
                            or validacao._RE_CLAUSULA.fullmatch("## " + visible_text)):
            impediments.append("titulo_sem_estilo_comprovado")
        if body and (style == "GovDocsAssinatura" or "____" in text):
            signature_section = True
        block_clause, block_section = (clause, section) if body else (None, "institucional")
        view_text = "## " + visible_text if heading and body else visible_text
        reason = ("institucional" if not body or style in INSTITUTIONAL_STYLES else
                  "titulo" if heading else "assinatura" if signature_section else
                  "preambulo" if block_clause is None else
                  "paragrafo_nao_suportado" if not _paragrafo_uniforme(block) else None)
        result.append(BlocoGovernado(f"{doc_key}/{block_section}/{anchor.block_id}",
                    "titulo" if heading and body else "paragrafo", block_clause, view_text,
                    hash_texto(view_text), anchor, reason))
    fixed = perfis.clausulas_fixas(doc_key)
    if fixed and not set(fixed).issubset(occurrences):
        # Partial numbering must not disguise a later fixed/signature region as
        # ordinary text belonging to an editable earlier clause.
        impediments.append("perfil_fixed_sem_estrutura")
    # The Markdown policy helper receives numbered clauses only. Native
    # unnumbered headings (e.g. ASSINATURAS) and their following paragraphs are
    # already blocked as heading/preamble, and must not introduce None into its
    # numbered-clause set.
    blocked = set(achados.caminhos_bloqueados(doc_key,
                  [b.canonico() for b in result if b.clausula is not None]))
    result = tuple(BlocoGovernado(b.path, b.tipo, b.clausula, b.conteudo, b.hash, b.ancora,
                   "clausula_bloqueada" if b.path in blocked else b.bloqueio) for b in result)
    return ProjecaoNativa(doc_key, indice.document_id, indice.revision, indice.content_hash,
            indice.engine_manifest_sha256, result, "\n\n".join(b.conteudo for b in result),
            tuple(sorted(set(gaps))), tuple(sorted(set(impediments))))


def snapshot_nativo(projecoes: dict[str, ProjecaoNativa], *, versao: int) -> dict:
    """Canonical policy snapshot whose bundle hash binds native revision/build."""
    _inteiro(versao, minimum=1)
    if (not isinstance(projecoes, dict) or not projecoes
            or any(not isinstance(p, ProjecaoNativa) or key != p.documento for key, p in projecoes.items())):
        raise ErroAncora("Projeções inválidas para snapshot nativo.")
    bindings = {key: projecoes[key].vinculo() for key in sorted(projecoes)}
    return {"versao": versao, "hash": _fingerprint(bindings),
            "documentos": {key: value.snapshot_documento() for key, value in projecoes.items()}}
