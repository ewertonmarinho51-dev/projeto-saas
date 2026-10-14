"""Contrato da ponte; não concede ACL nem substitui persistência/CAS do servidor.

Instância deve pertencer a uma única sessão autenticada/documento. Somente o
backend chama ``confirmar_checkpoint`` após commit persistido. O navegador
nunca pode emitir ACK. Ainda não conectado ao editor de produção.
"""
from __future__ import annotations

import base64
import binascii
import hashlib
import hmac
import copy
from dataclasses import dataclass, field
from urllib.parse import urlsplit
from uuid import UUID

PROTOCOL = "gc-wordcraft/v1"
MAX_BYTES = 8 * 1024 * 1024
MAX_EVENTS = 10_000
EVENTS = frozenset({"document.loaded", "document.changed", "document.checkpoint", "document.retry"})
CHECKPOINT_SCHEMA = "gc-wordcraft-snapshot/v1"
FIELDS = frozenset({"protocol", "request_id", "instance_id", "session_id",
                    "document_id", "expected_revision", "event", "sequence",
                    "nonce", "payload"})


class ErroPonte(ValueError):
    """Entrada recusada; o documento persistido não foi alterado."""


def _inteiro(value, minimum=0):
    if type(value) is not int or value < minimum or value > 2**53 - 1:
        raise ErroPonte("Inteiro inválido no protocolo.")
    return value


def _uuid(value):
    if not isinstance(value, str) or len(value) != 36:
        raise ErroPonte("Identificador inválido.")
    try:
        if str(UUID(value)) != value:
            raise ErroPonte("Identificador não canônico.")
    except ValueError as exc:
        raise ErroPonte("Identificador inválido.") from exc
    return value


def _hash(value):
    if (not isinstance(value, str) or len(value) != 64
            or any(c not in "0123456789abcdef" for c in value)):
        raise ErroPonte("Hash inválido.")
    return value


def _campos(value, fields):
    if not isinstance(value, dict) or value.keys() != fields:
        raise ErroPonte("Campos inesperados ou ausentes.")


@dataclass(frozen=True)
class Checkpoint:
    request_id: str
    expected_revision: int
    content_hash: str
    content: bytes = field(repr=False)


@dataclass
class Ponte:
    origin: str
    instance_id: str
    session_id: str
    document_id: str
    nonce: str = field(repr=False)
    revision: int = 0
    content_hash: str = ""
    state: str = field(default="opening", init=False)
    sequence: int = field(default=0, init=False)
    _seen: set[str] = field(default_factory=set, init=False, repr=False)
    _pending: Checkpoint | None = field(default=None, init=False, repr=False)
    _changed_while_saving: bool = field(default=False, init=False, repr=False)
    _last_ack: tuple[str, int, str] | None = field(default=None, init=False, repr=False)

    def __post_init__(self):
        if not isinstance(self.origin, str):
            raise ErroPonte("Origem explícita obrigatória.")
        parsed = urlsplit(self.origin)
        if (parsed.scheme not in {"http", "https"} or not parsed.netloc
                or parsed.username or parsed.password
                or self.origin != f"{parsed.scheme}://{parsed.netloc}"):
            raise ErroPonte("Origem explícita obrigatória.")
        for value in (self.instance_id, self.session_id, self.document_id):
            _uuid(value)
        if (not isinstance(self.nonce, str) or not self.nonce.isascii()
                or not 32 <= len(self.nonce) <= 128):
            raise ErroPonte("Nonce inválido.")
        _inteiro(self.revision)
        _hash(self.content_hash)

    def receber(self, event: dict, *, origin: str, source_ok: bool) -> Checkpoint | None:
        """``source_ok`` só pode vir da verificação event.source do host confiável.

        O adaptador servidor ainda deve verificar sessão, ACL e versão no banco.
        Estes controles locais não são prova de isolamento de tenants.
        """
        if source_ok is not True or origin != self.origin:
            raise ErroPonte("Origem ou janela recusada.")
        _campos(event, FIELDS)
        if (event["protocol"] != PROTOCOL or not isinstance(event["event"], str)
                or event["event"] not in EVENTS):
            raise ErroPonte("Protocolo ou evento recusado.")
        for key in ("instance_id", "session_id", "document_id"):
            if event[key] != getattr(self, key):
                raise ErroPonte("Escopo divergente.")
        if (not isinstance(event["nonce"], str) or not event["nonce"].isascii()
                or not hmac.compare_digest(event["nonce"], self.nonce)):
            raise ErroPonte("Nonce recusado.")
        request = _uuid(event["request_id"])
        seq = _inteiro(event["sequence"], 1)
        revision = _inteiro(event["expected_revision"])
        if request in self._seen or seq <= self.sequence:
            raise ErroPonte("Replay recusado.")
        if len(self._seen) >= MAX_EVENTS:
            raise ErroPonte("Renovação controlada da sessão necessária.")
        if revision != self.revision:
            raise ErroPonte("Revisão divergente; recarregar de forma controlada.")
        payload = event["payload"]
        kind = event["event"]
        checkpoint = None
        if kind == "document.loaded":
            _campos(payload, {"content_hash"})
            if self.state != "opening" or _hash(payload["content_hash"]) != self.content_hash:
                raise ErroPonte("Documento carregado diverge do autorizado.")
            next_state = "ready"
        elif kind == "document.changed":
            _campos(payload, set())
            if self.state not in {"ready", "dirty", "saved", "saving", "error"}:
                raise ErroPonte("Documento indisponível para edição.")
            next_state = (self.state if self._pending else "dirty")
        elif kind == "document.retry":
            _campos(payload, {"request_id"})
            if (self.state != "error" or not self._pending
                    or payload["request_id"] != self._pending.request_id):
                raise ErroPonte("Retry não corresponde ao checkpoint pendente.")
            checkpoint = self._pending
            next_state = "saving"
        else:
            _campos(payload, {"content_hash", "content_base64", "schema_version"})
            if self.state != "dirty" or self._pending:
                raise ErroPonte("Checkpoint indisponível neste estado.")
            if payload["schema_version"] != CHECKPOINT_SCHEMA:
                raise ErroPonte("Schema não suportado.")
            digest = _hash(payload["content_hash"])
            encoded = payload["content_base64"]
            if not isinstance(encoded, str) or len(encoded) > 4 * ((MAX_BYTES + 2) // 3):
                raise ErroPonte("Payload excede limite.")
            try:
                content = base64.b64decode(encoded, validate=True)
            except (ValueError, binascii.Error) as exc:
                raise ErroPonte("Bytes inválidos.") from exc
            if not content or len(content) > MAX_BYTES:
                raise ErroPonte("Payload vazio ou excessivo.")
            if hashlib.sha256(content).hexdigest() != digest:
                raise ErroPonte("Conteúdo não corresponde ao hash.")
            checkpoint = Checkpoint(request, revision, digest, content)
            next_state = "saving"
        # Nenhum estado é consumido antes de todas as validações.
        self._seen.add(request)
        self.sequence = seq
        self.state = next_state
        if kind == "document.changed" and self._pending:
            self._changed_while_saving = True
        if checkpoint and kind == "document.checkpoint":
            self._pending = checkpoint
            self._changed_while_saving = False
        return checkpoint

    def receber_lote(self, batch: dict, *, origin: str, source_ok: bool) -> Checkpoint | None:
        """Aceita estado coalescido sem perder eventos ou consumir lote inválido.

        O renderer devolve ``event_ack=self.sequence`` somente após este método
        aceitar o lote. Isso confirma transporte, nunca gravação ou aprovação.
        Prefixos já consumidos podem reaparecer em reruns; eventos novos mantêm
        todas as validações de receber. No máximo um checkpoint por lote.
        """
        if source_ok is not True or origin != self.origin:
            raise ErroPonte("Origem ou janela recusada.")
        _campos(batch, {"events"})
        events = batch["events"]
        if not isinstance(events, list) or not 1 <= len(events) <= 256:
            raise ErroPonte("Lote vazio ou excessivo.")
        candidate = copy.deepcopy(self)
        checkpoint = None
        previous = 0
        encoded_size = 0
        for event in events:
            _campos(event, FIELDS)
            request_id = _uuid(event["request_id"])
            payload = event["payload"]
            if isinstance(payload, dict) and isinstance(payload.get("content_base64"), str):
                encoded_size += len(payload["content_base64"])
                if encoded_size > 2 * MAX_BYTES:
                    raise ErroPonte("Lote excede limite de bytes.")
            sequence = _inteiro(event["sequence"], 1)
            if sequence <= previous:
                raise ErroPonte("Lote fora de ordem.")
            previous = sequence
            if sequence <= self.sequence:
                if (request_id not in self._seen
                        or any(event[key] != getattr(self, key) for key in
                               ("instance_id", "session_id", "document_id", "nonce"))):
                    raise ErroPonte("Prefixo do lote não pertence a esta instância.")
                continue
            if sequence != candidate.sequence + 1:
                raise ErroPonte("Lote perdeu um evento.")
            accepted = candidate.receber(event, origin=origin, source_ok=source_ok)
            if accepted is not None:
                if checkpoint is not None:
                    raise ErroPonte("Mais de um checkpoint no lote.")
                checkpoint = accepted
        self.__dict__.update(candidate.__dict__)
        return checkpoint

    def confirmar_checkpoint(self, *, request_id: str, revision: int, content_hash: str):
        """Somente resposta confiável do commit CAS, nunca evento do navegador."""
        pending = self._pending
        _inteiro(revision, 1)
        _hash(content_hash)
        if (self.state not in {"saving", "error"} or not pending or request_id != pending.request_id
                or revision != pending.expected_revision + 1
                or content_hash != pending.content_hash):
            raise ErroPonte("ACK não corresponde ao checkpoint persistido.")
        self.revision = revision
        self.content_hash = content_hash
        self._last_ack = (request_id, revision, content_hash)
        self._pending = None
        self.state = "dirty" if self._changed_while_saving else "saved"

    def ack_persistido(self) -> dict | None:
        """Cópia da última confirmação aceita do proprietário backend."""
        if self._last_ack is None:
            return None
        request_id, revision, content_hash = self._last_ack
        return dict(request_id=request_id, revision=revision, content_hash=content_hash)

    def falha_pendente(self) -> dict | None:
        if self._pending is None or self.state not in {"error", "conflict"}:
            return None
        return dict(request_id=self._pending.request_id, conflict=self.state == "conflict")

    def falhar_checkpoint(self, *, request_id: str, conflict: bool = False):
        """Não descarta bytes: falha transitória permite retry do mesmo checkpoint."""
        if not self._pending or request_id != self._pending.request_id:
            raise ErroPonte("Falha não correlacionada.")
        self.state = "conflict" if conflict else "error"

    def repetir_checkpoint(self) -> Checkpoint:
        """Retry conserva id/bytes para idempotência no backend, sem nova revisão local."""
        if self.state != "error" or not self._pending:
            raise ErroPonte("Retry indisponível.")
        self.state = "saving"
        return self._pending
