"""Experimental single owner of native document opening/checkpoint commits.

No operational consumer is enabled. Reuses the existing user's JWT client and
private server client. Only verified user context reaches the internal commit RPC.
Draft commits never approve documents or overwrite legacy process documents.
"""
from dataclasses import dataclass, field
import hashlib
from pathlib import Path
import re
from uuid import NAMESPACE_URL, uuid5

from . import db
from .wordcraft_native import validar
from .wordcraft_protocol import Checkpoint, MAX_BYTES, _uuid, _hash

SCHEMA = "gc-wordcraft-snapshot/v1"
UPSTREAM = "533615620ef91ae57fa7aa4cd77fd98b2179e693"


class ErroDocumento(RuntimeError):
    pass


class AcessoNegado(ErroDocumento):
    pass


class ConflitoDocumento(ErroDocumento):
    pass


@dataclass(frozen=True)
class Documento:
    id: str
    processo_id: str
    tipo: str
    revision: int
    content_hash: str
    status: str
    payload: bytes = field(repr=False)


@dataclass(frozen=True)
class Recibo:
    document_id: str
    request_id: str
    revision: int
    content_hash: str
    replayed: bool


def _execute(query):
    try:
        return query.execute().data
    except Exception as error:
        if getattr(error, "code", None) in {"40001", "23505"}:
            raise ConflitoDocumento("A revisão ou operação documental divergiu.") from None
        if getattr(error, "code", None) == "42501":
            raise AcessoNegado("Operação documental não autorizada.") from None
        # Database/API errors can contain request bodies. Never echo or log them.
        raise ErroDocumento("Não foi possível concluir a operação documental.") from None


def _one(rows):
    if not isinstance(rows, list) or len(rows) != 1 or not isinstance(rows[0], dict):
        raise AcessoNegado("Documento não disponível nesta sessão.")
    return rows[0]


class DocumentoService:
    def __init__(self, *, node: Path, bundle: Path, manifest_sha256: str):
        # Configuration is supplied by the trusted server, never component data.
        self._native = dict(node=node, bundle=bundle, manifest_sha256=manifest_sha256)

    def _session(self):
        user = db.cliente_do_usuario()
        if user is None:
            raise AcessoNegado("Sessão autenticada obrigatória para o documento.")
        context = _execute(user.rpc("documento_editor_contexto", {}))
        try:
            if (not isinstance(context, dict) or context.keys() != {"sub", "role", "app_metadata"}
                    or context["role"] != "authenticated" or not isinstance(context["app_metadata"], dict)):
                raise ValueError()
            _uuid(context["sub"])
            _uuid(context["app_metadata"]["tenant_id"])
        except (ValueError, KeyError, TypeError):
            raise AcessoNegado("Contexto documental não verificado.") from None
        return user, context

    def _head(self, user, document_id):
        _uuid(document_id)
        return _one(_execute(user.table("documentos_editor")
                             .select("id,processo_id,tipo,revision,content_hash,status")
                             .eq("id", document_id).limit(1)))

    def _validate(self, payload):
        if not isinstance(payload, bytes) or not 0 < len(payload) <= MAX_BYTES:
            raise ErroDocumento("Checkpoint vazio ou excessivo.")
        try:
            validar(payload, **self._native)
        except Exception:
            raise ErroDocumento("O motor não confirmou a validade do documento.") from None

    def abrir(self, document_id: str) -> Documento:
        user, _ = self._session()
        head = self._head(user, document_id)
        revision = head["revision"]
        if type(revision) is not int or revision < 1:
            raise ErroDocumento("Revisão documental inválida.")
        row = _one(_execute(user.table("documentos_editor_revisoes")
                            .select("payload,content_hash,editor_schema_version,wordcraft_commit")
                            .eq("document_id", document_id).eq("revision", revision).limit(1)))
        encoded = row.get("payload")
        if (not isinstance(encoded, str) or not encoded.startswith("\\x")
                or not 2 < len(encoded) <= 2 * MAX_BYTES + 2
                or row.get("editor_schema_version") != SCHEMA or row.get("wordcraft_commit") != UPSTREAM):
            raise ErroDocumento("Formato documental não suportado pelo motor pinado.")
        try:
            payload = bytes.fromhex(encoded[2:])
        except ValueError:
            raise ErroDocumento("Payload documental inválido.") from None
        digest = hashlib.sha256(payload).hexdigest()
        if digest != row.get("content_hash") or digest != head.get("content_hash"):
            raise ErroDocumento("Hash documental divergente.")
        self._validate(payload)
        return Documento(head["id"], head["processo_id"], head["tipo"], revision,
                         digest, head["status"], payload)

    def _commit(self, *, document_id, process_id, tipo, checkpoint, context):
        _uuid(document_id)
        _uuid(process_id)
        _uuid(checkpoint.request_id)
        _hash(checkpoint.content_hash)
        if (not isinstance(checkpoint.content, bytes) or not 0 < len(checkpoint.content) <= MAX_BYTES
                or type(checkpoint.expected_revision) is not int or checkpoint.expected_revision < 0
                or hashlib.sha256(checkpoint.content).hexdigest() != checkpoint.content_hash):
            raise ErroDocumento("Contrato de checkpoint divergente.")
        self._validate(checkpoint.content)
        row = _one(_execute(db._cliente().rpc("documento_editor_checkpoint", {
            "p_document": document_id, "p_process": process_id, "p_tipo": tipo,
            "p_expected_revision": checkpoint.expected_revision, "p_operation": checkpoint.request_id,
            "p_payload": "\\x" + checkpoint.content.hex(), "p_content_hash": checkpoint.content_hash,
            "p_claims": context,
        })))
        if (row.keys() != {"document_id", "revision", "content_hash", "operation_id", "replayed"}
                or row["document_id"] != document_id or row["operation_id"] != checkpoint.request_id
                or type(row["revision"]) is not int or row["revision"] != checkpoint.expected_revision + 1
                or row["content_hash"] != checkpoint.content_hash or type(row["replayed"]) is not bool):
            raise ErroDocumento("Resposta de commit documental divergente.")
        return Recibo(document_id, row["operation_id"], row["revision"], row["content_hash"], row["replayed"])

    def criar(self, *, processo_id: str, tipo: str, payload: bytes, operation_id: str) -> Documento:
        _uuid(processo_id)
        _uuid(operation_id)
        if not isinstance(tipo, str) or not re.fullmatch(r"[a-z][a-z0-9_]{0,63}", tipo):
            raise ErroDocumento("Tipo documental inválido.")
        user, context = self._session()
        _one(_execute(user.table("processos").select("id").eq("id", processo_id).limit(1)))
        document_id = str(uuid5(NAMESPACE_URL, "govconnect-document:" + processo_id + ":" + tipo))
        if not isinstance(payload, bytes):
            raise ErroDocumento("Payload documental inválido.")
        checkpoint = Checkpoint(operation_id, 0, hashlib.sha256(payload).hexdigest(), payload)
        self._commit(document_id=document_id, process_id=processo_id, tipo=tipo,
                     checkpoint=checkpoint, context=context)
        return self.abrir(document_id)

    def checkpoint(self, document_id: str, checkpoint: Checkpoint) -> Recibo:
        if not isinstance(checkpoint, Checkpoint):
            raise ErroDocumento("Checkpoint tipado obrigatório.")
        user, context = self._session()
        head = self._head(user, document_id)
        return self._commit(document_id=document_id, process_id=head["processo_id"], tipo=head["tipo"],
                            checkpoint=checkpoint, context=context)
