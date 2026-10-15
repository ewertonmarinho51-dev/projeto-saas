"""Experimental single owner of native document opening/checkpoint commits.

No operational consumer is enabled. Reuses the existing user's JWT client and
private server client. Only verified user context reaches the internal commit RPC.
Draft commits never approve documents or overwrite legacy process documents.
"""
from dataclasses import dataclass, field, replace
import hashlib
import json
from pathlib import Path
import re
from uuid import NAMESPACE_URL, uuid5

from . import db
from . import wordcraft_blocos as blocos
from .wordcraft_native import validar, exportar, importar_docx
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
    engine_build: str | None = None
    validation_provenance: str = "legacy_unrecorded"
    index: blocos.IndiceNativo | None = field(default=None, repr=False)
    index_mode: str = "legacy_unrecorded"
    restored_from_revision: int | None = None
    institutional_snapshot: dict | None = field(default=None, repr=False)
    institutional_snapshot_hash: str | None = None


@dataclass(frozen=True)
class Recibo:
    document_id: str
    request_id: str
    revision: int
    content_hash: str
    replayed: bool
    engine_build: str
    validation_provenance: str
    index_hash: str
    index_mode: str
    restored_from_revision: int | None
    original_hash: str | None
    index: blocos.IndiceNativo = field(repr=False)
    institutional_snapshot: dict | None = field(default=None, repr=False)
    institutional_snapshot_hash: str | None = None


@dataclass(frozen=True)
class FonteOriginal:
    formato: str
    content_hash: str
    payload: bytes = field(repr=False)
    relatorio: dict = field(repr=False)


@dataclass(frozen=True)
class Artefato:
    document_id: str
    revision: int
    source_hash: str
    formato: str
    content_hash: str
    engine_build: str
    payload: bytes = field(repr=False)
    source_engine_build: str | None = None
    source_validation_provenance: str = "legacy_unrecorded"
    institutional_snapshot_hash: str | None = None
    restored_from_revision: int | None = None
    restored_source_hash: str | None = None


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


def _provenance(row):
    """Historical validation and today's runtime are distinct facts."""
    build = row.get("engine_build_sha256")
    provenance = row.get("validation_provenance")
    if build is None and provenance == "legacy_unrecorded":
        return build, provenance
    if (isinstance(build, str) and re.fullmatch(r"[0-9a-f]{64}", build)
            and provenance == "server_manifest_sha256"):
        return build, provenance
    raise ErroDocumento("Proveniência documental inválida.")


def _snapshot_bytes(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")


def _snapshot_read(encoded, digest, *, document_id, process_id, tipo):
    if encoded is None and digest is None:
        return None
    try:
        if not isinstance(encoded, str) or not encoded.startswith("\\x") or len(encoded) > 2 * MAX_BYTES + 2:
            raise ValueError()
        raw = bytes.fromhex(encoded[2:])
        if not raw or hashlib.sha256(raw).hexdigest() != digest:
            raise ValueError()
        value = json.loads(raw, object_pairs_hook=blocos._objeto_fechado)
        if (value.keys() != {"schema", "phase", "application", "document_id", "processo_id", "tenant_id",
                "secretaria_id", "doc_key", "captured_for_revision", "reference_date", "identity", "signatories",
                "portaria", "signature_block"}
                or value["schema"] != "gc-wordcraft-institutional/v1" or value["phase"] != "draft_reference"
                or value["application"] not in {"reference_only", "applied_by_govconnect_docx"}
                or (value["document_id"], value["processo_id"], value["doc_key"]) != (document_id, process_id, tipo)
                or type(value["captured_for_revision"]) is not int or value["captured_for_revision"] < 1
                or not isinstance(value["identity"], dict) or not isinstance(value["signatories"], list)
                or not isinstance(value["signature_block"], str)):
            raise ValueError()
        _uuid(value["tenant_id"])
        if value["secretaria_id"] is not None:
            _uuid(value["secretaria_id"])
        return value
    except (ValueError, KeyError, TypeError, AttributeError, UnicodeError, RecursionError):
        raise ErroDocumento("Snapshot institucional divergente.") from None


class DocumentoService:
    def __init__(self, *, node: Path, bundle: Path, manifest_sha256: str):
        # Configuration is supplied by the trusted server, never component data.
        if not isinstance(manifest_sha256, str) or not re.fullmatch(r"[0-9a-f]{64}", manifest_sha256):
            raise ErroDocumento("Manifesto documental pinado obrigatório.")
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
                             .select("id,processo_id,tipo,revision,content_hash,status,tenant_id")
                             .eq("id", document_id).limit(1)))

    def _capturar_institucional(self, user, *, document_id, process_id, tipo, revision, application="reference_only"):
        from . import assinaturas, contexto, emissao, portarias
        try:
            process = _one(_execute(user.table("processos").select("id,tenant_id,secretaria_id,criado_em,dados")
                .eq("id", process_id).limit(1)))
            tenant, secretary = process["tenant_id"], process.get("secretaria_id")
            _uuid(tenant)
            if secretary is not None:
                _uuid(secretary)
            def catalog(table):
                rows = _execute(user.table(table).select("*").eq("tenant_id", tenant).limit(10001))
                if not isinstance(rows, list) or len(rows) > 10000 or any(not isinstance(row, dict) for row in rows):
                    raise ValueError()
                return rows
            units = [row for row in catalog("secretarias") if row.get("ativo", True)]
            identity, origin = contexto.resolver_identidade(units, secretary)
            reference = emissao.data_de_referencia(process)
            portaria = portarias.resolver(catalog("portarias"), secretaria_id=secretary, data_referencia=reference)
            data = process.get("dados") or {}
            choices = (data.get(emissao.CHAVE_ESCOLHA) or {}).get(tipo) or []
            if not isinstance(choices, list) or len(choices) > 100 or any(not isinstance(choice, dict) for choice in choices):
                raise ValueError()
            servers = catalog("servidores")
            assignments, members = catalog("servidor_funcoes"), catalog("portaria_membros")
            for choice in choices:
                eligible = assinaturas.elegiveis(funcao=choice.get("funcao"), servidores=servers,
                    funcoes_do_servidor=assignments, portaria=portaria, membros_da_portaria=members,
                    secretaria_id=secretary, data_referencia=reference)
                assinaturas.conferir_elegibilidade(servidor_id=choice.get("servidor_id"), funcao=choice.get("funcao"), elegiveis_agora=eligible)
            secretary_name = next((row.get("nome") for row in units if row.get("id") == secretary), None)
            signatories = emissao.montar_signatarios(choices, servidores=servers, secretaria_nome=secretary_name, portaria=portaria)
            if len(signatories) != len(choices):
                raise ValueError()
            value = {"schema": "gc-wordcraft-institutional/v1", "phase": "draft_reference", "application": application,
                "document_id": document_id, "processo_id": process_id, "tenant_id": tenant, "secretaria_id": secretary,
                "doc_key": tipo, "captured_for_revision": revision, "reference_date": reference.isoformat(),
                "identity": emissao.montar_identidade(identity, origin, secretaria_id=secretary),
                "signatories": signatories, "portaria": {key: portaria.get(key) for key in ("id", "numero", "ano", "tipo",
                    "status", "data_publicacao", "data_inicio_vigencia", "data_fim_vigencia", "secretaria_id")} if portaria else None,
                "signature_block": emissao.bloco_de_assinaturas(signatories)}
            raw = _snapshot_bytes(value)
            if len(raw) > MAX_BYTES:
                raise ValueError()
            return raw
        except Exception:
            raise ErroDocumento("Não foi possível confirmar o contexto institucional no backend.") from None

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
        return self._revision(user, head, head["revision"])

    def _revision(self, user, head, revision):
        if type(revision) is not int or revision < 1:
            raise ErroDocumento("Revisão documental inválida.")
        document_id = head["id"]
        row = _one(_execute(user.table("documentos_editor_revisoes")
                            .select("payload,content_hash,editor_schema_version,wordcraft_commit,"
                                    "engine_build_sha256,validation_provenance,block_index,block_index_sha256,"
                                    "index_mode,restored_from_revision,institutional_snapshot,institutional_snapshot_sha256")
                            .eq("document_id", document_id).eq("revision", revision).limit(1)))
        engine_build, provenance = _provenance(row)
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
        if digest != row.get("content_hash") or (revision == head["revision"] and digest != head.get("content_hash")):
            raise ErroDocumento("Hash documental divergente.")
        self._validate(payload)
        institutional = _snapshot_read(row.get("institutional_snapshot"), row.get("institutional_snapshot_sha256"),
            document_id=document_id, process_id=head["processo_id"], tipo=head["tipo"])
        if institutional and (institutional["tenant_id"] != head["tenant_id"] or institutional["captured_for_revision"] > revision):
            raise ErroDocumento("Snapshot institucional fora da revisão autorizada.")
        index = None
        mode = row.get("index_mode")
        if row.get("block_index") is None:
            if row.get("block_index_sha256") is not None or mode is not None:
                raise ErroDocumento("Índice documental incompleto.")
            mode = "legacy_unrecorded"
        else:
            try:
                encoded_index = bytes.fromhex(row["block_index"][2:]) if row["block_index"].startswith("\\x") else b""
                if hashlib.sha256(encoded_index).hexdigest() != row.get("block_index_sha256"):
                    raise ValueError()
                index = blocos.desserializar_indice(encoded_index)
                if ((index.document_id, index.revision, index.content_hash, index.engine_manifest_sha256)
                        != (document_id, revision, digest, engine_build)
                        or mode not in {"initial", "reconciled", "rebuilt_missing_index", "rebuilt_build"}):
                    raise ValueError()
                if engine_build == self._native["manifest_sha256"]:
                    blocos.validar_indice(index, payload, **self._native)
            except Exception:
                raise ErroDocumento("Índice documental divergente.") from None
        return Documento(head["id"], head["processo_id"], head["tipo"], revision,
                         digest, head["status"], payload, engine_build, provenance, index, mode,
                         row.get("restored_from_revision"), institutional, row.get("institutional_snapshot_sha256"))

    def _commit(self, *, document_id, process_id, tipo, checkpoint, context, user,
                original=None, restored_from=None, institutional=None):
        _uuid(document_id)
        _uuid(process_id)
        _uuid(checkpoint.request_id)
        _hash(checkpoint.content_hash)
        if (not isinstance(checkpoint.content, bytes) or not 0 < len(checkpoint.content) <= MAX_BYTES
                or type(checkpoint.expected_revision) is not int or checkpoint.expected_revision < 0
                or hashlib.sha256(checkpoint.content).hexdigest() != checkpoint.content_hash):
            raise ErroDocumento("Contrato de checkpoint divergente.")
        base = None
        if checkpoint.expected_revision:
            base = self._revision(user, self._head(user, document_id), checkpoint.expected_revision)
        try:
            if base and base.index and base.engine_build == self._native["manifest_sha256"]:
                index = blocos.reconciliar_indice(base.index, base.payload, checkpoint.content,
                    revision=checkpoint.expected_revision + 1, content_hash=checkpoint.content_hash, **self._native)
                index_mode = "reconciled"
            else:
                index = blocos.construir_indice(checkpoint.content, document_id=document_id,
                    revision=checkpoint.expected_revision + 1, content_hash=checkpoint.content_hash, **self._native)
                index_mode = "initial" if base is None else "rebuilt_missing_index"
                if base and base.index:
                    index_mode = "rebuilt_build"
                    index = replace(index, invalidacoes=tuple(blocos.Invalidacao(b.block_id, "build_alterado") for b in base.index.blocos))
            encoded_index = blocos.serializar_indice(index)
        except Exception:
            raise ErroDocumento("O motor não confirmou o índice da revisão.") from None
        index_hash = hashlib.sha256(encoded_index).hexdigest()
        institutional_value, institutional_hash = None, None
        if institutional is None and restored_from is None and base and base.institutional_snapshot:
            institutional = _snapshot_bytes(base.institutional_snapshot)
        if institutional is None and checkpoint.expected_revision == 0:
            prior = _execute(user.table("documentos_editor_revisoes")
                .select("institutional_snapshot,institutional_snapshot_sha256")
                .eq("document_id", document_id).eq("operation_id", checkpoint.request_id).limit(1))
            if prior:
                stored = _one(prior)
                institutional_value = _snapshot_read(stored.get("institutional_snapshot"), stored.get("institutional_snapshot_sha256"),
                    document_id=document_id, process_id=process_id, tipo=tipo)
                if institutional_value:
                    institutional = _snapshot_bytes(institutional_value)
        if institutional is None:
            institutional = self._capturar_institucional(user, document_id=document_id, process_id=process_id,
                tipo=tipo, revision=checkpoint.expected_revision + 1)
        institutional_hash = hashlib.sha256(institutional).hexdigest()
        institutional_value = _snapshot_read("\\x" + institutional.hex(), institutional_hash,
            document_id=document_id, process_id=process_id, tipo=tipo)
        params = {
            "p_document": document_id, "p_process": process_id, "p_tipo": tipo,
            "p_expected_revision": checkpoint.expected_revision, "p_operation": checkpoint.request_id,
            "p_payload": "\\x" + checkpoint.content.hex(), "p_content_hash": checkpoint.content_hash,
            "p_claims": context,
            "p_engine_build_sha256": self._native["manifest_sha256"],
            "p_block_index": "\\x" + encoded_index.hex(), "p_block_index_sha256": index_hash,
            "p_index_mode": index_mode, "p_original_format": original.formato if original else None,
            "p_original_payload": "\\x" + original.payload.hex() if original else None,
            "p_conversion_report": original.relatorio if original else None,
            "p_restored_from_revision": restored_from,
        }
        fields = {"document_id", "revision", "content_hash", "operation_id", "replayed",
                          "engine_build_sha256", "validation_provenance", "block_index_sha256",
                          "index_mode", "restored_from_revision", "original_hash"}
        params.update(p_institutional_snapshot="\\x" + institutional.hex(), p_institutional_snapshot_sha256=institutional_hash)
        fields.add("institutional_snapshot_sha256")
        row = _one(_execute(db._cliente().rpc("documento_editor_checkpoint", params)))
        if (row.keys() != fields
                or row["document_id"] != document_id or row["operation_id"] != checkpoint.request_id
                or type(row["revision"]) is not int or row["revision"] != checkpoint.expected_revision + 1
                or row["content_hash"] != checkpoint.content_hash or type(row["replayed"]) is not bool
                or row["engine_build_sha256"] != self._native["manifest_sha256"]
                or row["validation_provenance"] != "server_manifest_sha256"
                or row["block_index_sha256"] != index_hash or row["index_mode"] != index_mode
                or row["restored_from_revision"] != restored_from
                or row["original_hash"] != (original.content_hash if original else None)
                or (row["institutional_snapshot_sha256"] != institutional_hash)):
            raise ErroDocumento("Resposta de commit documental divergente.")
        return Recibo(document_id, row["operation_id"], row["revision"], row["content_hash"], row["replayed"],
                      row["engine_build_sha256"], row["validation_provenance"], index_hash, index_mode,
                      restored_from, row["original_hash"], index, institutional_value, institutional_hash)

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
                     checkpoint=checkpoint, context=context, user=user)
        return self.abrir(document_id)

    def checkpoint(self, document_id: str, checkpoint: Checkpoint) -> Recibo:
        if not isinstance(checkpoint, Checkpoint):
            raise ErroDocumento("Checkpoint tipado obrigatório.")
        user, context = self._session()
        head = self._head(user, document_id)
        return self._commit(document_id=document_id, process_id=head["processo_id"], tipo=head["tipo"],
                            checkpoint=checkpoint, context=context, user=user)

    def abrir_revisao(self, document_id: str, revision: int) -> Documento:
        user, _ = self._session()
        return self._revision(user, self._head(user, document_id), revision)

    def restaurar(self, document_id: str, *, source_revision: int, expected_revision: int,
                  operation_id: str) -> Recibo:
        user, context = self._session()
        head = self._head(user, document_id)
        if (type(expected_revision) is not int or type(source_revision) is not int
                or not 1 <= source_revision <= expected_revision):
            raise ErroDocumento("Revisão de restauração inválida.")
        source = self._revision(user, head, source_revision)
        checkpoint = Checkpoint(operation_id, expected_revision, source.content_hash, source.payload)
        return self._commit(document_id=document_id, process_id=head["processo_id"], tipo=head["tipo"],
            checkpoint=checkpoint, context=context, user=user, restored_from=source_revision,
            institutional=_snapshot_bytes(source.institutional_snapshot) if source.institutional_snapshot else None)

    def importar_legado(self, *, processo_id: str, tipo: str, operation_id: str,
                        formato: str, original_docx: bytes | None = None) -> Documento:
        """Single explicit import. Markdown always comes from authorized legacy storage."""
        from .config import DOCUMENTOS
        from .export import gerar_docx
        _uuid(processo_id)
        _uuid(operation_id)
        if tipo not in DOCUMENTOS or formato not in {"markdown", "docx"}:
            raise ErroDocumento("Fonte legada não suportada.")
        user, context = self._session()
        process = _one(_execute(user.table("processos").select("id,documentos").eq("id", processo_id).limit(1)))
        if formato == "markdown":
            if original_docx is not None:
                raise ErroDocumento("Markdown deve vir do processo autorizado.")
            documents = process.get("documentos")
            text = documents.get(tipo) if isinstance(documents, dict) else None
            if not isinstance(text, str) or not text:
                raise ErroDocumento("Original Markdown ausente.")
            original = text.encode("utf-8")
            if len(original) > MAX_BYTES:
                raise ErroDocumento("Original excede o limite documental.")
        else:
            original = original_docx
            if not isinstance(original, bytes) or not 0 < len(original) <= MAX_BYTES:
                raise ErroDocumento("Original DOCX inválido ou excessivo.")
        report = {"schema": "gc-wordcraft-import/v1", "source_format": formato,
            "source_sha256": hashlib.sha256(original).hexdigest(), "fidelity": "pending_manual_review",
            "pipeline": "govconnect_docx_wordcraft" if formato == "markdown" else "wordcraft_docx"}
        source = FonteOriginal(formato, report["source_sha256"], original, report)
        doc_id = str(uuid5(NAMESPACE_URL, "govconnect-document:" + processo_id + ":" + tipo))
        recorded = _execute(user.table("documentos_editor_revisoes").select("revision,original_format,original_payload,original_hash,conversion_report")
            .eq("document_id", doc_id).eq("operation_id", operation_id).limit(1))
        institutional = None
        if recorded:
            row = _one(recorded)
            if (row.get("revision") != 1 or row.get("original_format") != formato
                    or row.get("original_payload") != "\\x" + original.hex()
                    or row.get("original_hash") != source.content_hash or row.get("conversion_report") != report):
                raise ConflitoDocumento("Operação de importação já vinculada a outra fonte.")
            persisted = self._revision(user, self._head(user, doc_id), 1)
            content = persisted.payload
            if persisted.institutional_snapshot:
                institutional = _snapshot_bytes(persisted.institutional_snapshot)
        else:
            try:
                branding, signatures = None, ""
                institutional = self._capturar_institucional(user, document_id=doc_id, process_id=processo_id,
                    tipo=tipo, revision=1, application="applied_by_govconnect_docx" if formato == "markdown" else "reference_only")
                value = json.loads(institutional)
                branding, signatures = value["identity"]["identidade"], value["signature_block"]
                docx = gerar_docx(DOCUMENTOS[tipo]["titulo"], text, branding=branding, assinaturas=signatures) if formato == "markdown" else original
                content = importar_docx(docx, **self._native)
            except Exception:
                raise ErroDocumento("Importação recusada pelo motor; original legado preservado.") from None
        checkpoint = Checkpoint(operation_id, 0, hashlib.sha256(content).hexdigest(), content)
        self._commit(document_id=doc_id, process_id=processo_id, tipo=tipo, checkpoint=checkpoint,
                     context=context, user=user, original=source, institutional=institutional)
        return self.abrir(doc_id)

    def original(self, document_id: str, revision: int) -> FonteOriginal:
        user, _ = self._session()
        self._revision(user, self._head(user, document_id), revision)
        row = _one(_execute(user.table("documentos_editor_revisoes")
            .select("original_format,original_payload,original_hash,conversion_report")
            .eq("document_id", document_id).eq("revision", revision).limit(1)))
        try:
            if not isinstance(row["original_payload"], str) or not row["original_payload"].startswith("\\x"):
                raise ValueError()
            payload = bytes.fromhex(row["original_payload"][2:])
            if (row["original_format"] not in {"markdown", "docx"} or not 0 < len(payload) <= MAX_BYTES
                    or hashlib.sha256(payload).hexdigest() != row["original_hash"]
                    or not isinstance(row["conversion_report"], dict)
                    or row["conversion_report"].get("source_sha256") != row["original_hash"]
                    or row["conversion_report"].get("source_format") != row["original_format"]):
                raise ValueError()
            return FonteOriginal(row["original_format"], row["original_hash"], payload, row["conversion_report"])
        except (ValueError, TypeError, KeyError):
            raise ErroDocumento("Original não registrado ou divergente.") from None

    def exportar(self, document_id: str, *, expected_revision: int, content_hash: str, formato: str) -> Artefato:
        """Export an exact persisted draft; never approves or marks official emission."""
        if formato not in {"docx", "pdf"}:
            raise ErroDocumento("Formato documental não autorizado.")
        document = self.abrir(document_id)
        if (type(expected_revision) is not int or document.revision != expected_revision
                or document.content_hash != content_hash):
            raise ConflitoDocumento("A revisão persistida mudou antes da exportação.")
        try:
            payload = exportar(document.payload, formato=formato, **self._native)
        except Exception:
            raise ErroDocumento("O motor não confirmou a exportação documental.") from None
        restored_source = self.abrir_revisao(document_id, document.restored_from_revision) if document.restored_from_revision else None
        return Artefato(document.id, document.revision, document.content_hash, formato,
                        hashlib.sha256(payload).hexdigest(), self._native["manifest_sha256"], payload,
                        document.engine_build, document.validation_provenance, document.institutional_snapshot_hash,
                        document.restored_from_revision, restored_source.content_hash if restored_source else None)
