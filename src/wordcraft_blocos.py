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
from typing import Callable
from uuid import UUID, uuid5

from .blocos import hash_texto
from .wordcraft_native import validar
from .wordcraft_protocol import CHECKPOINT_SCHEMA, MAX_BYTES, _hash, _inteiro, _uuid

INDEX_SCHEMA = "gc-wordcraft-block-index/v1"
MAX_BLOCOS = 20_000
MAX_DEPTH = 32
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
