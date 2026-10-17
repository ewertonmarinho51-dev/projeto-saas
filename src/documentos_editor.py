"""Single owner of native document revisions, review, export and emission.

Reuses the existing user's JWT client and private server client. Only verified
user context reaches internal mutation RPCs. Draft commits never approve or
emit documents, and the native path never overwrites legacy process content.
"""
from dataclasses import dataclass, field, replace
from datetime import datetime, timezone
import hashlib
import hmac
import io
import json
from pathlib import Path
import re
import secrets
from uuid import NAMESPACE_URL, uuid5
from weakref import WeakValueDictionary
from zipfile import ZIP_DEFLATED, ZipFile, ZipInfo

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
class VinculoAprovacao:
    document_id: str
    revision: int
    content_hash: str
    operation_id: str


@dataclass(frozen=True)
class Aprovacao:
    id: str
    document_id: str
    revision: int
    content_hash: str
    operation_id: str
    institutional_snapshot_hash: str
    event_id: str
    replayed: bool
    status: str = "aprovado"
    institutional_snapshot: dict | None = field(default=None, repr=False)
    quality: dict | None = field(default=None, repr=False)


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
    approval: Aprovacao | None = field(default=None, repr=False)


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


@dataclass(frozen=True)
class PacoteArtefatos:
    processo_id: str
    formato: str
    content_hash: str
    manifest: dict = field(repr=False)
    payload: bytes = field(repr=False)


@dataclass(frozen=True)
class Emissao:
    id: str
    processo_id: str
    operation_id: str
    docx_sha256: str
    pdf_sha256: str
    event_id: str
    replayed: bool
    manifest: dict = field(repr=False)
    docx: PacoteArtefatos = field(repr=False)
    pdf: PacoteArtefatos = field(repr=False)


@dataclass(frozen=True)
class FontePatch:
    doc_key: str
    document_id: str
    revision: int
    content_hash: str
    engine_build: str
    index_hash: str
    institutional_hash: str


@dataclass(frozen=True)
class ResultadoPatch:
    fonte: FontePatch
    revision: int
    content_hash: str
    index_hash: str
    payload: bytes = field(repr=False)
    index: blocos.IndiceNativo = field(repr=False)
    institutional_snapshot: bytes = field(repr=False)


@dataclass(frozen=True)
class ComandoPatch:
    fonte: FontePatch
    operation_id: str
    target_revision: int
    target_hash: str
    _plano_json: bytes = field(repr=False)

    def plano_nativo(self) -> dict:
        """Copy of the canonical applicator's exact compiled command envelope."""
        return json.loads(self._plano_json)


@dataclass(frozen=True)
class PreparacaoPatches:
    operation_id: str
    processo_id: str
    actor_id: str
    plan_hash: str
    source_bundle_hash: str
    target_bundle_hash: str
    fontes: tuple[FontePatch, ...]
    resultados: tuple[ResultadoPatch, ...] = field(repr=False)
    comandos: tuple[ComandoPatch, ...] = field(repr=False)
    _contexto_json: bytes = field(repr=False)
    _auditoria_json: bytes = field(repr=False)
    _selo: str = field(repr=False)

    def auditoria(self) -> dict:
        return json.loads(self._auditoria_json)

    def __reduce_ex__(self, protocol):
        raise TypeError("Preparação exige a instância viva do owner; não pode ser serializada.")


@dataclass(frozen=True)
class ReciboPatches:
    operation_id: str
    processo_id: str
    audit_id: str
    plan_hash: str
    replayed: bool
    documentos: tuple[Recibo, ...] = field(repr=False)
    canvas_confirmado: bool = False


def _execute(query):
    try:
        return query.execute().data
    except Exception as error:
        if getattr(error, "code", None) in {"PT409", "40001", "23505", "55P03", "57014"}:
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


def _vincular_achado_nativo(finding: dict, views: dict, texts: dict) -> dict:
    """Translate a legacy finding only through exact block parity.

    ``consistencia`` remains the rule owner and addresses its legacy text view.
    The browser supplies none of this mapping. A path becomes executable only
    when the complete legacy block has exactly one equal, editable native
    paragraph in the same numbered clause. Any uncertainty remains manual.
    """
    from . import blocos as blocos_legados

    result = dict(finding)
    doc_key = result.get("documentId")
    view = views.get(doc_key) if isinstance(doc_key, str) else None
    text = texts.get(doc_key) if isinstance(doc_key, str) else None
    source_paths = result.get("allowedPaths")
    if (view is None or not isinstance(text, str) or not isinstance(source_paths, list)
            or not result.get("autoCorrectable") or not source_paths
            or not result.get("sourceIds")):
        result.update(autoCorrectable=False, allowedPaths=[], blockedPaths=[])
        return result

    legacy = {block["path"]: block
              for block in blocos_legados.dividir_em_blocos(doc_key, text)}
    mapped = []
    for path in source_paths:
        block = legacy.get(path)
        if block is None:
            mapped = []
            break
        candidates = [native for native in view.blocos
            if native.clausula == block.get("clausula")
            and native.conteudo == block.get("conteudo")
            and native.bloqueio is None]
        if len(candidates) != 1:
            mapped = []
            break
        mapped.append(candidates[0].path)
    if not mapped or len(set(mapped)) != len(mapped):
        result.update(autoCorrectable=False, allowedPaths=[], blockedPaths=[])
        return result
    result.update(autoCorrectable=True, allowedPaths=mapped, blockedPaths=[])
    return result


def _alvo_objetivo_parecer(item, texts: dict) -> list[str]:
    """Narrow a clause-wide opinion to one block quoted by its evidence."""
    from . import blocos as blocos_legados

    if not item.documento or item.documento not in texts:
        return []
    evidences = [value.strip() for value in item.evidencias
                 if isinstance(value, str) and len(value.strip()) >= 16]
    if not evidences:
        return []
    candidates = [block["path"] for block in blocos_legados.dividir_em_blocos(
        item.documento, texts[item.documento])
        if block["path"] in item.caminhos
        and any(evidence in block["conteudo"] for evidence in evidences)]
    return candidates if len(set(candidates)) == 1 else []


class DocumentoService:
    def __init__(self, *, node: Path, bundle: Path, manifest_sha256: str):
        # Configuration is supplied by the trusted server, never component data.
        if not isinstance(manifest_sha256, str) or not re.fullmatch(r"[0-9a-f]{64}", manifest_sha256):
            raise ErroDocumento("Manifesto documental pinado obrigatório.")
        self._native = dict(node=node, bundle=bundle, manifest_sha256=manifest_sha256)
        self._patch_key = secrets.token_bytes(32)
        self._preparacoes: WeakValueDictionary[str, PreparacaoPatches] = WeakValueDictionary()
        self._patch_pendentes: dict[str, PreparacaoPatches] = {}

    def _fontes_patch(self, processo_id, user, claims):
        context = _execute(db._cliente().rpc("documento_editor_fontes_patch",
            {"p_process": processo_id, "p_claims": claims}))
        if (not isinstance(context, dict) or context.keys() != {"processo", "fatos"}
                or not isinstance(context["processo"], dict)
                or context["processo"].get("id") != processo_id
                or not isinstance(context["fatos"], list) or len(context["fatos"]) > 10000
                or len(_snapshot_bytes(context)) > MAX_BYTES):
            raise ErroDocumento("Fontes backend de patch incompletas.")
        heads = _execute(user.table("documentos_editor")
            .select("id,processo_id,tipo,revision,content_hash,status,tenant_id")
            .eq("processo_id", processo_id).limit(33))
        if not isinstance(heads, list) or not 1 <= len(heads) <= 32:
            raise ErroDocumento("Conjunto nativo vazio ou excessivo.")
        originals = {}
        for head in sorted(heads, key=lambda d: d["id"]):
            if head.get("processo_id") != processo_id or head.get("tipo") in originals:
                raise ErroDocumento("Mapeamento documental ambíguo.")
            doc = self._revision(user, head, head["revision"])
            if (not doc.index or not doc.institutional_snapshot
                    or doc.engine_build != self._native["manifest_sha256"]):
                raise ErroDocumento("Uma fonte não possui índice, contexto e build atuais comprovados.")
            originals[doc.tipo] = doc
        views = {key: blocos.projetar_documento(key, doc.payload,
            indice=doc.index, **self._native) for key,doc in originals.items()}
        if any(not view.apto_analise for view in views.values()):
            raise ErroDocumento("Cobertura textual incompleta nas fontes do patch.")
        return context, originals, views

    def auditoria_atual(self, processo_id: str) -> dict:
        """Read-only contextual report bound to current native revisions."""
        _uuid(processo_id)
        user, claims = self._session()
        context, _, views = self._fontes_patch(processo_id, user, claims)
        snapshot = blocos.snapshot_nativo(views, versao=1)
        report = self._auditar_patches(processo_id, views, context, version=1)
        return json.loads(_snapshot_bytes({"report": report, "snapshot": snapshot}))

    def pareceres_atuais(self, processo_id: str) -> dict:
        """Project persisted legal-opinion findings onto current native heads."""
        _uuid(processo_id)
        user, claims = self._session()
        context, _, views = self._fontes_patch(processo_id, user, claims)
        return json.loads(_snapshot_bytes(self._relatorio_pareceres(
            processo_id, user, context, views, version=1)))

    def _relatorio_pareceres(self, processo_id, user, context, views, *, version):
        """Re-read legal findings and bind them to the supplied native views."""
        from . import parecer_correcao

        opinions = _execute(user.table("pareceres")
            .select("id,nome_arquivo,hash_origem,status")
            .eq("processo_id", processo_id).eq("status", "NORMALIZED").limit(17))
        if (not isinstance(opinions, list) or len(opinions) > 16
                or len(_snapshot_bytes(opinions)) > MAX_BYTES):
            raise ErroDocumento("Conjunto de pareceres vazio ou excessivo.")
        texts = {key: view.texto_analise for key, view in views.items()}
        findings, sources = [], []
        for opinion in opinions:
            try:
                opinion_id = str(_uuid(opinion["id"]))
                if opinion.keys() != {"id", "nome_arquivo", "hash_origem", "status"}:
                    raise ValueError()
                if (not isinstance(opinion["nome_arquivo"], str)
                        or len(opinion["nome_arquivo"]) > 255
                        or opinion["status"] != "NORMALIZED"):
                    raise ValueError()
                _hash(opinion["hash_origem"])
                rows = _execute(user.table("parecer_achados").select(
                    "id,categoria,gravidade,problema,documento_afetado,clausula_afetada,"
                    "fundamento,correcao_solicitada,causa,sistemico,confianca,evidencias")
                    .eq("parecer_id", opinion_id).limit(101))
                expected = {"id", "categoria", "gravidade", "problema",
                    "documento_afetado", "clausula_afetada", "fundamento",
                    "correcao_solicitada", "causa", "sistemico", "confianca", "evidencias"}
                if (not isinstance(rows, list) or len(rows) > 100
                        or any(not isinstance(row, dict) or row.keys() != expected for row in rows)
                        or len(_snapshot_bytes(rows)) > MAX_BYTES):
                    raise ValueError()
                situated = parecer_correcao.situar(rows, texts,
                    context["processo"].get("dados") or {})
                if len(situated) != len(rows):
                    raise ValueError()
            except (KeyError, TypeError, ValueError):
                raise ErroDocumento("Parecer contextual incompleto ou excessivo.") from None
            sources.append({"parecerId": opinion_id,
                "nomeArquivo": str(opinion["nome_arquivo"])[:255],
                "hashOrigem": str(opinion["hash_origem"]), "status": opinion["status"]})
            for row, item in zip(rows, situated):
                targets = (_alvo_objetivo_parecer(item, texts)
                           if item.situacao == parecer_correcao.CORRECAO_AUTOMATICA else [])
                finding = {"findingId": f"PJ:{opinion_id}:{_uuid(row['id'])}",
                    "documentId": item.documento, "clauseId": item.clausula or None,
                    "categoria": "parecer_juridico", "severity": item.gravidade,
                    "descricao": item.problema, "evidencia": list(item.evidencias),
                    "regraViolada": item.fundamento,
                    "resultadoEsperado": item.recomendacao,
                    "autoCorrectable": bool(targets),
                    "allowedPaths": targets, "blockedPaths": [],
                    "sourceIds": [f"parecer:{opinion_id}", f"parecer_achado:{row['id']}"],
                    "blockingReason": (item.motivo or None) if targets else
                        (item.motivo or "O parecer não contém citação única do bloco a corrigir."),
                    "parecerStatus": item.situacao}
                findings.append(_vincular_achado_nativo(finding, views, texts))
        snapshot = blocos.snapshot_nativo(views, versao=version)
        return {"schema": "gc-wordcraft-legal-opinions/v1",
            "bundleId": processo_id, "bundleVersion": version,
            "bundleHash": snapshot["hash"], "status": "REVIEW_COMPLETED",
            "sourceNative": {
                key: view.vinculo() for key, view in views.items()},
            "pareceres": sources, "findings": findings,
            "officialEmission": False}

    def evidencias_atuais(self, processo_id: str) -> dict:
        """Read current canonical facts as source evidence for the panel."""
        from .wordcraft_capacidades import ErroCapacidade, evidencia_fato

        _uuid(processo_id)
        user, claims = self._session()
        context, _, views = self._fontes_patch(processo_id, user, claims)
        try:
            evidence = [evidencia_fato(fact) for fact in context["fatos"]
                        if fact.get("status") != "substituido"]
        except (AttributeError, ErroCapacidade):
            raise ErroDocumento("Fontes factuais incompletas para o painel.") from None
        snapshot = blocos.snapshot_nativo(views, versao=1)
        return json.loads(_snapshot_bytes({"schema": "gc-wordcraft-evidence-panel/v1",
            "bundleHash": snapshot["hash"], "sourceNative": {
                key: view.vinculo() for key, view in views.items()},
            "evidencias": evidence}))

    def atendimentos_parecer(self, processo_id: str) -> dict:
        """Derive immutable legal-opinion attendance from committed patch audits."""
        _uuid(processo_id)
        user, _ = self._session()
        rows = _execute(user.table("revisoes").select(
            "id,criado_em,native_patch_operation,native_patch_actor,relatorios,planos,diffs")
            .eq("processo_id", processo_id).order("criado_em", desc=True).limit(51))
        if (not isinstance(rows, list) or len(rows) > 50
                or len(_snapshot_bytes(rows)) > MAX_BYTES * 4):
            raise ErroDocumento("Histórico de atendimento excessivo.")
        reports = []
        expected = {"id", "criado_em", "native_patch_operation", "native_patch_actor",
                    "relatorios", "planos", "diffs"}
        try:
            for row in rows:
                if not isinstance(row, dict) or row.keys() != expected:
                    raise ValueError()
                if row["native_patch_operation"] is None:
                    continue
                audit_id = str(_uuid(row["id"]))
                operation = str(_uuid(row["native_patch_operation"]))
                actor = str(_uuid(row["native_patch_actor"]))
                relatorios, planos, diffs = row["relatorios"], row["planos"], row["diffs"]
                if (not isinstance(relatorios, list) or len(relatorios) != 2
                        or not isinstance(planos, list) or len(planos) != 1
                        or not isinstance(diffs, list) or len(diffs) != 1):
                    raise ValueError()
                before, after = relatorios
                if before.get("schema") != "gc-wordcraft-legal-opinions/v1":
                    continue
                if after.get("schema") != before["schema"]:
                    raise ValueError()
                plan = planos[0]
                if plan.get("patchPlanId") != operation:
                    raise ValueError()
                operations = plan.get("operations")
                if not isinstance(operations, list):
                    raise ValueError()
                applied = {item["findingId"] for item in operations
                           if isinstance(item, dict) and isinstance(item.get("findingId"), str)}
                post = {item["findingId"]: item for item in after.get("findings", [])
                        if isinstance(item, dict) and isinstance(item.get("findingId"), str)}
                items = []
                for finding in before.get("findings", []):
                    finding_id = finding["findingId"]
                    later = post.get(finding_id)
                    if finding_id in applied and later is not None and not later.get("autoCorrectable"):
                        status = "APLICADO_PENDENTE_REVISAO"
                        reason = ("Operação persistida e alvo anterior encerrado; "
                                  "o atendimento jurídico ainda exige revisão humana.")
                    elif finding_id in applied:
                        status = "NAO_COMPROVADO"
                        reason = "Operação persistida, mas a revalidação não comprovou o atendimento."
                    else:
                        status = "PENDENTE"
                        reason = finding.get("blockingReason") or "Apontamento não incluído no plano aplicado."
                    items.append({"findingId": finding_id, "status": status,
                        "reason": reason, "sourceIds": list(finding.get("sourceIds") or ())})
                reports.append({"auditId": audit_id, "operationId": operation,
                    "actorId": actor, "createdAt": row["criado_em"],
                    "items": items, "diff": diffs[0]})
        except (AttributeError, KeyError, TypeError, ValueError):
            raise ErroDocumento("Histórico jurídico divergente.") from None
        return json.loads(_snapshot_bytes({"schema": "gc-wordcraft-legal-attendance/v1",
            "processId": processo_id, "reports": reports}))

    def estrutura_atual(self, processo_id: str, doc_key: str) -> dict:
        """Read the revision-bound institution and deterministic item assembly."""
        from .wordcraft_capacidades import ErroCapacidade, montar_itens

        _uuid(processo_id)
        if not isinstance(doc_key, str) or not doc_key:
            raise ErroDocumento("Tipo documental inválido para montagem.")
        user, claims = self._session()
        context, originals, views = self._fontes_patch(processo_id, user, claims)
        document = originals.get(doc_key)
        if document is None or document.institutional_snapshot is None:
            raise ErroDocumento("Documento não possui snapshot institucional atual.")
        data = context["processo"].get("dados") or {}
        items = data.get("itens") or []
        if not isinstance(items, list) or len(items) > 10000:
            raise ErroDocumento("Itens do processo inválidos ou excessivos.")
        try:
            assembly = montar_itens(items)
        except ErroCapacidade as error:
            raise ErroDocumento(str(error)) from None
        artifacts = _execute(user.table("governanca_artefatos")
            .select("id,tenant_id,secretaria_id,chave_estavel,descricao")
            .eq("tipo_artefato", "template").limit(101))
        if (not isinstance(artifacts, list) or len(artifacts) > 100
                or len(_snapshot_bytes(artifacts)) > MAX_BYTES):
            raise ErroDocumento("Biblioteca de templates excessiva.")
        templates = []
        for artifact in artifacts:
            try:
                artifact_id = _uuid(artifact["id"])
                if artifact.keys() != {"id", "tenant_id", "secretaria_id",
                        "chave_estavel", "descricao"}:
                    raise ValueError()
                _uuid(artifact["tenant_id"])
                if artifact["secretaria_id"] is not None:
                    _uuid(artifact["secretaria_id"])
                if (not isinstance(artifact["chave_estavel"], str)
                        or not artifact["chave_estavel"]
                        or len(artifact["chave_estavel"]) > 200
                        or not isinstance(artifact["descricao"], str)
                        or len(artifact["descricao"]) > 1000):
                    raise ValueError()
                versions = _execute(user.table("governanca_versoes")
                    .select("id,artefato_id,versao,status,vigencia_inicio,vigencia_fim,hash,payload")
                    .eq("artefato_id", artifact_id).eq("status", "PUBLISHED").limit(17))
                if (not isinstance(versions, list) or len(versions) > 16
                        or len(_snapshot_bytes(versions)) > MAX_BYTES):
                    raise ValueError()
                for version in versions:
                    _uuid(version["id"])
                    _hash(version["hash"])
                    if (version["artefato_id"] != artifact_id
                            or type(version["versao"]) is not int or version["versao"] < 1
                            or version["status"] != "PUBLISHED"
                            or not isinstance(version["payload"], dict)
                            or not isinstance(version["payload"].get("blocos"), list)):
                        raise ValueError()
                    templates.append({"artifactId": artifact_id,
                        "versionId": version["id"], "key": artifact["chave_estavel"],
                        "description": artifact["descricao"], "version": version["versao"],
                        "status": version["status"], "hash": version["hash"],
                        "validFrom": version["vigencia_inicio"], "validTo": version["vigencia_fim"],
                        "scope": "secretaria" if artifact["secretaria_id"] else "municipio",
                        "blockCount": len(version["payload"].get("blocos") or [])})
            except (KeyError, TypeError, ValueError):
                raise ErroDocumento("Biblioteca de templates divergente.") from None
        snapshot = blocos.snapshot_nativo(views, versao=1)
        return json.loads(_snapshot_bytes({"schema": "gc-wordcraft-structure-panel/v1",
            "bundleHash": snapshot["hash"], "sourceNative": {
                key: view.vinculo() for key, view in views.items()},
            "documentId": document.id, "docKey": doc_key,
            "institucional": document.institutional_snapshot,
            "montagem": assembly, "templatesPublicados": templates,
            "templateEfetivo": None,
            "templateBlockingReason": (
                "Nenhum vínculo canônico tipo documental → chave de template está registrado."
                if templates else "Nenhum template publicado está visível para esta sessão.")}))

    def _auditar_patches(self, process_id, views, context, *, version):
        from . import achados, consistencia, validacao
        texts = {key: view.texto_analise for key, view in views.items()}
        snapshot = blocos.snapshot_nativo(views, versao=version)
        raw = validacao.validar_todos(texts, {}, context["processo"].get("dados") or {})
        findings = achados.estruturar(raw, texts,
            blocos_por_documento={key: [b.canonico() for b in view.blocos] for key,view in views.items()})
        by_path = {b.path: b for view in views.values() for b in view.blocos}
        for finding in findings:
            finding["allowedPaths"] = [p for p in finding["allowedPaths"] if p in by_path and by_path[p].bloqueio is None]
            finding["autoCorrectable"] = bool(finding["autoCorrectable"] and finding["allowedPaths"])
        for finding in consistencia.verificar(context["fatos"], texts):
            findings.append(_vincular_achado_nativo(finding, views, texts))
        return {"bundleId": process_id, "bundleVersion": version, "bundleHash": snapshot["hash"],
            "status": "REVIEW_COMPLETED", "findings": findings, "validatorFindings": raw,
            "validatorVersion": validacao.versao_do_auditor(), "model": "validacao-deterministica",
            "sourceNative": {key: view.vinculo() for key,view in views.items()},
            "coverage": {key: {"text": view.apto_analise, "gaps": list(view.areas_nao_cobertas),
                "structuralTableAudit": False} for key,view in views.items()}, "officialEmission": False}

    def _selo_patches(self, prep):
        value = {"operation": prep.operation_id, "process": prep.processo_id, "actor": prep.actor_id,
            "plan": prep.plan_hash, "source": prep.source_bundle_hash, "target": prep.target_bundle_hash,
            "fontes": [vars(f) for f in prep.fontes],
            "resultados": [{"fonte": vars(r.fonte), "revision": r.revision, "hash": r.content_hash,
                "index_hash": r.index_hash, "payload": hashlib.sha256(r.payload).hexdigest(),
                "index": hashlib.sha256(blocos.serializar_indice(r.index)).hexdigest(),
                "institutional": hashlib.sha256(r.institutional_snapshot).hexdigest()} for r in prep.resultados],
            "comandos": [{"fonte": vars(c.fonte), "op": c.operation_id, "rev": c.target_revision,
                "hash": c.target_hash, "plano": hashlib.sha256(c._plano_json).hexdigest()} for c in prep.comandos],
            "context": hashlib.sha256(prep._contexto_json).hexdigest(),
            "audit": hashlib.sha256(prep._auditoria_json).hexdigest()}
        return hmac.new(self._patch_key, _snapshot_bytes(value), hashlib.sha256).hexdigest()

    def preparar_patches(self, processo_id: str, *, operation_id: str, propor_plano) -> PreparacaoPatches:
        return self._preparar_patches(processo_id, operation_id=operation_id,
            propor_plano=propor_plano, origem="auditoria")

    def preparar_parecer(self, processo_id: str, *, operation_id: str, propor_plano) -> PreparacaoPatches:
        """Prepare one legal-opinion correction through the canonical G4 owner."""
        return self._preparar_patches(processo_id, operation_id=operation_id,
            propor_plano=propor_plano, origem="parecer")

    def _preparar_patches(self, processo_id: str, *, operation_id: str,
                          propor_plano, origem: str) -> PreparacaoPatches:
        """Prepare entirely on the trusted backend. No persistence or canvas ACK."""
        from . import corretor, patches
        _uuid(processo_id)
        _uuid(operation_id)
        if not callable(propor_plano):
            raise ErroDocumento("Propositor backend obrigatório.")
        user, claims = self._session()
        if operation_id in self._preparacoes:
            previous = self._preparacoes[operation_id]
            if (previous.processo_id, previous.actor_id) != (processo_id, claims["sub"]):
                raise ConflitoDocumento("Operação de patch já pertence a outra preparação.")
            if previous.auditoria().get("origem") != origem:
                raise ConflitoDocumento("Operação de patch já pertence a outra origem contextual.")
            return previous
        if len(self._patch_pendentes) >= 4:
            raise ErroDocumento("Há quatro preparações pendentes; conclua ou descarte uma preparação.")
        context, originals, views = self._fontes_patch(processo_id, user, claims)
        before = blocos.snapshot_nativo(views, versao=1)
        report = (self._relatorio_pareceres(processo_id, user, context, views, version=1)
                  if origem == "parecer" else
                  self._auditar_patches(processo_id, views, context, version=1))
        try:
            proposal = propor_plano(relatorio=json.loads(_snapshot_bytes(report)),
                snapshot=json.loads(_snapshot_bytes(before)), contexto=json.loads(_snapshot_bytes(context)))
            if not isinstance(proposal, dict) or proposal.keys() - {"operations", "unresolvedFindings"}:
                raise ValueError()
            plan = corretor._envelope(proposal.get("operations"), proposal.get("unresolvedFindings", []), report, before)
            plan.update(patchPlanId=operation_id, sourceNative={key: view.vinculo() for key,view in views.items()})
            for op in plan["operations"]:
                source = originals[op["documentId"]]
                if source.status not in {"rascunho", "em_revisao"} or source.tipo in context["processo"].get("aprovados", []):
                    raise AcessoNegado("Documento aprovado não pode receber patch automático.")
            applied = patches.aplicar_plano_nativo(plan,
                {key: blocos.DocumentoNativo(d.payload,d.index) for key,d in originals.items()}, report, **self._native)
            changed = sorted(applied["comandos"])
            if not changed or set(applied["documentos"]) != set(originals):
                raise ValueError()
            sources, results, commands = [], [], []
            for key,doc in originals.items():
                source = FontePatch(key,doc.id,doc.revision,doc.content_hash,doc.engine_build,
                    hashlib.sha256(blocos.serializar_indice(doc.index)).hexdigest(), doc.institutional_snapshot_hash)
                sources.append(source)
                target = applied["documentos"][key]
                if key not in changed:
                    if target.checkpoint != doc.payload or target.indice != doc.index:
                        raise ValueError()
                    continue
                index = target.indice
                if ((index.document_id,index.revision,index.content_hash,index.engine_manifest_sha256)
                        != (doc.id,doc.revision+1,hashlib.sha256(target.checkpoint).hexdigest(),doc.engine_build)
                        or {(b.block_id,b.caminho,b.story_kind,b.tipo) for b in index.blocos}
                        != {(b.block_id,b.caminho,b.story_kind,b.tipo) for b in doc.index.blocos}):
                    raise ValueError()
                blocos.validar_indice(index,target.checkpoint,**self._native)
                results.append(ResultadoPatch(source,index.revision,index.content_hash,
                    hashlib.sha256(blocos.serializar_indice(index)).hexdigest(),target.checkpoint,index,
                    _snapshot_bytes(doc.institutional_snapshot)))
                commands.append(ComandoPatch(source,operation_id,index.revision,index.content_hash,
                    _snapshot_bytes(applied["comandos"][key])))
            after_views = {key: blocos.projetar_documento(key,d.checkpoint,indice=d.indice,**self._native)
                for key,d in applied["documentos"].items()}
            post = (self._relatorio_pareceres(
                        processo_id, user, context, after_views, version=2)
                    if origem == "parecer" else
                    self._auditar_patches(processo_id,after_views,context,version=2))
            audit = {"schema":"gc-wordcraft-patch-batch/v1", "operation_id":operation_id,
                "origem":origem,
                "plan":plan,"reports":[report,post],"snapshots":[before,applied["snapshot"]],"diff":applied["diff"],
                "status":"REVIEW_COMPLETED","official_emission":False}
            prep = PreparacaoPatches(operation_id,processo_id,claims["sub"],hashlib.sha256(_snapshot_bytes(plan)).hexdigest(),
                before["hash"],applied["snapshot"]["hash"],tuple(sources),tuple(results),tuple(commands),
                _snapshot_bytes(context),_snapshot_bytes(audit),"")
            if sum(len(r.payload)+len(blocos.serializar_indice(r.index))+len(r.institutional_snapshot)
                    for r in prep.resultados)+len(prep._auditoria_json)>32*1024*1024:
                raise ValueError()
            prep = replace(prep,_selo=self._selo_patches(prep))
        except ErroDocumento:
            raise
        except Exception:
            raise ErroDocumento("Preparação nativa recusada; nenhuma revisão foi gravada.") from None
        self._preparacoes[operation_id] = prep
        self._patch_pendentes[operation_id] = prep
        return prep

    def descartar_patches(self, preparacao: PreparacaoPatches) -> None:
        """Revoke this in-memory preparation without any persistence or ACK."""
        if (not isinstance(preparacao, PreparacaoPatches)
                or self._preparacoes.get(preparacao.operation_id) is not preparacao):
            raise ErroDocumento("Preparação não pertence a este owner.")
        self._patch_pendentes.pop(preparacao.operation_id, None)
        del self._preparacoes[preparacao.operation_id]

    def confirmar_patches(self, preparacao: PreparacaoPatches, *, checkpoints: dict[str, Checkpoint] | None = None) -> ReciboPatches:
        """One SQL transaction for all targets and source CAS. Never ACKs a host."""
        prep = preparacao
        try:
            if (not isinstance(prep, PreparacaoPatches) or self._preparacoes.get(prep.operation_id) is not prep
                    or not hmac.compare_digest(prep._selo, self._selo_patches(prep))):
                raise ValueError()
        except Exception:
            raise ErroDocumento("Preparação não pertence a este owner ou foi alterada.") from None
        user, claims = self._session()
        if claims["sub"] != prep.actor_id:
            raise AcessoNegado("Preparação pertence a outro ator.")
        if any(s.engine_build != self._native["manifest_sha256"] for s in prep.fontes):
            raise ConflitoDocumento("O build mudou depois da preparação.")
        if checkpoints is not None:
            if not isinstance(checkpoints, dict) or set(checkpoints) != {r.fonte.doc_key for r in prep.resultados}:
                raise ErroDocumento("Confirmações do host não cobrem exatamente o lote preparado.")
            for result in prep.resultados:
                checkpoint = checkpoints[result.fonte.doc_key]
                if (not isinstance(checkpoint, Checkpoint)
                        or (checkpoint.request_id,checkpoint.expected_revision,checkpoint.content_hash,checkpoint.content)
                        != (prep.operation_id,result.fonte.revision,result.content_hash,result.payload)):
                    raise ConflitoDocumento("O canvas não confirmou os bytes exatos da preparação.")
        batch = {"schema":"gc-wordcraft-patch-batch/v1", "operation_id":prep.operation_id,
            "processo_id":prep.processo_id,"actor_id":prep.actor_id,"plan_hash":prep.plan_hash,
            "source_bundle_hash":prep.source_bundle_hash,"target_bundle_hash":prep.target_bundle_hash,
            "sources":[vars(s) for s in prep.fontes],"context":json.loads(prep._contexto_json),
            "audit":json.loads(prep._auditoria_json),"targets":[]}
        batch["plan_payload"] = "\\x" + _snapshot_bytes(batch["audit"]["plan"]).hex()
        commands = {c.fonte.doc_key:c for c in prep.comandos}
        for result in prep.resultados:
            batch["targets"].append({"doc_key":result.fonte.doc_key,"document_id":result.fonte.document_id,
                "source_revision":result.fonte.revision,"revision":result.revision,"content_hash":result.content_hash,
                "payload":"\\x"+result.payload.hex(),"block_index":"\\x"+blocos.serializar_indice(result.index).hex(),
                "index_hash":result.index_hash,"institutional_snapshot":"\\x"+result.institutional_snapshot.hex(),
                "institutional_hash":result.fonte.institutional_hash,
                "engine_build":result.fonte.engine_build,"native_commands":commands[result.fonte.doc_key].plano_nativo()})
        raw = _snapshot_bytes(batch)
        digest = hashlib.sha256(raw).hexdigest()
        if len(raw)>64*1024*1024:
            raise ErroDocumento("Lote de persistência excessivo.")
        response = _execute(db._cliente().rpc("documento_editor_patch_lote", {
            "p_process":prep.processo_id,"p_operation":prep.operation_id,"p_batch":"\\x"+raw.hex(),
            "p_batch_sha256":digest,"p_claims":claims}))
        fields = {"operation_id","processo_id","audit_id","plan_hash","batch_sha256","replayed","documentos"}
        if (not isinstance(response, dict) or response.keys()!=fields
                or (response["operation_id"],response["processo_id"],response["plan_hash"],response["batch_sha256"])
                != (prep.operation_id,prep.processo_id,prep.plan_hash,digest)
                or type(response["replayed"]) is not bool or not isinstance(response["documentos"],list)
                or len(response["documentos"])!=len(prep.resultados)):
            raise ErroDocumento("Recibo de lote divergente.")
        try:
            _uuid(response["audit_id"])
            received = {row["document_id"]:row for row in response["documentos"]}
            if len(received)!=len(prep.resultados): raise ValueError()
            receipts=[]
            for result in prep.resultados:
                row=received[result.fonte.document_id]
                if row != {"document_id":result.fonte.document_id,"revision":result.revision,
                    "content_hash":result.content_hash,"engine_build_sha256":result.fonte.engine_build,
                    "block_index_sha256":result.index_hash,"index_mode":"operational_patch",
                    "institutional_snapshot_sha256":result.fonte.institutional_hash}:
                    raise ValueError()
                receipts.append(Recibo(result.fonte.document_id,prep.operation_id,result.revision,result.content_hash,
                    response["replayed"],result.fonte.engine_build,"server_manifest_sha256",result.index_hash,
                    "operational_patch",None,None,result.index,json.loads(result.institutional_snapshot),
                    result.fonte.institutional_hash))
        except (ValueError,KeyError,TypeError):
            raise ErroDocumento("Recibo documental do lote divergente.") from None
        self._patch_pendentes.pop(prep.operation_id, None)
        return ReciboPatches(prep.operation_id,prep.processo_id,response["audit_id"],prep.plan_hash,
            response["replayed"],tuple(receipts),checkpoints is not None)

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

    def _capturar_institucional(self, user, *, document_id, process_id, tipo, revision, application="reference_only", fontes=None):
        from . import assinaturas, contexto, emissao, portarias
        try:
            process = (fontes["processo"] if fontes is not None else
                _one(_execute(user.table("processos").select("id,tenant_id,secretaria_id,criado_em,dados")
                .eq("id", process_id).limit(1))))
            tenant, secretary = process["tenant_id"], process.get("secretaria_id")
            _uuid(tenant)
            if secretary is not None:
                _uuid(secretary)
            def catalog(table):
                rows = (fontes[table] if fontes is not None else
                    _execute(user.table(table).select("*").eq("tenant_id", tenant).limit(10001)))
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

    def listar_processo(self, processo_id: str) -> tuple[Documento, ...]:
        """Heads nativos visíveis na sessão; nunca mistura outro processo."""
        _uuid(processo_id)
        user, _ = self._session()
        heads = _execute(user.table("documentos_editor")
            .select("id,processo_id,tipo,revision,content_hash,status,tenant_id")
            .eq("processo_id", processo_id).limit(33))
        if (not isinstance(heads, list) or len(heads) > 32
                or any(not isinstance(head, dict)
                       or head.get("processo_id") != processo_id for head in heads)):
            raise ErroDocumento("Conjunto documental nativo inválido.")
        documents = [self._revision(user, head, head["revision"]) for head in heads]
        if len({document.tipo for document in documents}) != len(documents):
            raise ErroDocumento("Mapeamento documental nativo ambíguo.")
        return tuple(sorted(documents, key=lambda document: document.tipo))

    def texto_aprovado(self, document_id: str) -> tuple[str, str]:
        """Projeção textual do head aprovado para consumidores source-aware."""
        document = self.abrir(document_id)
        if document.status not in {"aprovado", "emitido"} or document.approval is None or not document.index:
            raise ErroDocumento("Revisão nativa ainda não possui aprovação comprovada.")
        try:
            view = blocos.projetar_documento(document.tipo, document.payload,
                indice=document.index, **self._native)
        except Exception:
            raise ErroDocumento("Projeção do documento aprovado foi recusada.") from None
        if not view.apto_analise or not view.texto_analise.strip():
            raise ErroDocumento("Cobertura textual aprovada incompleta.")
        return document.tipo, view.texto_analise

    def aprovar(self, vinculo: VinculoAprovacao) -> Aprovacao:
        """Individual review act. It never emits or advances the legacy process."""
        from . import achados, conhecimento, consistencia, politicas, qualidade, validacao
        if not isinstance(vinculo, VinculoAprovacao):
            raise ErroDocumento("Vínculo nativo tipado obrigatório para aprovação.")
        try:
            _uuid(vinculo.document_id)
            _uuid(vinculo.operation_id)
            _hash(vinculo.content_hash)
        except ValueError:
            raise ErroDocumento("Vínculo de aprovação inválido.") from None
        if type(vinculo.revision) is not int or vinculo.revision < 1:
            raise ErroDocumento("Revisão inválida para aprovação.")
        user, claims = self._session()
        head = self._head(user, vinculo.document_id)
        if (head["revision"], head["content_hash"]) != (vinculo.revision, vinculo.content_hash):
            raise ConflitoDocumento("A revisão mudou; reabra o documento antes de aprovar.")
        params = dict(p_document=vinculo.document_id, p_revision=vinculo.revision,
            p_content_hash=vinculo.content_hash, p_operation=vinculo.operation_id, p_claims=claims)
        if head["status"] in {"aprovado", "emitido"}:
            # Replay is checked by the transaction against the recorded actor and
            # operation. Current registry changes must not rewrite an old act.
            params.update(p_sources=None, p_snapshot=None, p_snapshot_sha256=None, p_evidence=None)
        else:
            document = self._revision(user, head, vinculo.revision)
            if (document.status not in {"rascunho", "em_revisao"} or document.index is None
                    or document.engine_build != self._native["manifest_sha256"]
                    or document.institutional_snapshot is None):
                raise ErroDocumento("A revisão não possui provas atuais para aprovação nativa.")
            sources = _execute(db._cliente().rpc("documento_editor_fontes_aprovacao",
                {"p_document": document.id, "p_claims": claims}))
            tables = {"secretarias", "servidores", "servidor_funcoes", "portarias", "portaria_membros",
                      "fatos_canonicos", "regras_conhecimento", "fontes_conhecimento", "config_app",
                      "governanca_artefatos", "governanca_versoes"}
            if (not isinstance(sources, dict) or sources.keys() != tables | {"processo"}
                    or any(not isinstance(sources[t], list) or len(sources[t]) > 10000 for t in tables)
                    or len(_snapshot_bytes(sources)) > MAX_BYTES):
                raise ErroDocumento("Fontes backend incompletas para aprovação.")
            current = json.loads(self._capturar_institucional(user, document_id=document.id,
                process_id=document.processo_id, tipo=document.tipo, revision=document.revision, fontes=sources))
            reference = document.institutional_snapshot
            ignored = {"application", "captured_for_revision"}
            if {k:v for k,v in current.items() if k not in ignored} != {k:v for k,v in reference.items() if k not in ignored}:
                raise ConflitoDocumento("O contexto institucional mudou; uma nova revisão explícita é necessária.")
            try:
                projection = blocos.projetar_documento(document.tipo, document.payload, indice=document.index, **self._native)
                if not projection.apto_analise:
                    raise ValueError()
                documents = {document.tipo: projection.texto_analise}
                facts = [f for f in sources["fatos_canonicos"] if f.get("status") != "substituido"]
                if not facts or any(f.get("status") != "confirmado" for f in facts):
                    raise ValueError()
                revoked = {str(value) for f in sources["fontes_conhecimento"] if not f.get("vigente", True)
                           for value in (f.get("id"), f.get("rotulo")) if value is not None}
                rules = conhecimento.regras_base() + sources["regras_conhecimento"]
                visual = any(str(c.get("valor", "")).strip().lower() in {"1", "true", "on", "sim"}
                    for c in sources["config_app"] if c.get("chave") == "flag_visual_policy_builder")
                if visual:
                    for artifact in sources["governanca_artefatos"]:
                        versions = [v for v in sources["governanca_versoes"]
                            if v.get("artefato_id") == artifact["id"] and v.get("status") == "PUBLISHED"]
                        if versions:
                            rules.append(politicas.como_regra(artifact, max(versions, key=lambda v: v["versao"])))
                evaluated_at = datetime.now(timezone.utc)
                decision = conhecimento.resolver(facts, rules, revoked,
                    processo_id=document.processo_id, documento=document.tipo, agora=evaluated_at)
                raw_findings = validacao.validar_todos(documents, {}, sources["processo"].get("dados") or {})
                # The structured classifier may not yet know a newer blocking
                # validator message. Preserve the canonical raw verdict too.
                if validacao.bloqueios(raw_findings):
                    raise ValueError()
                findings = achados.estruturar(raw_findings, documents)
                findings += consistencia.verificar(facts, documents)
                report = {"findings": findings}
                result = qualidade.calcular(report, facts, decision, documents)
                gate = qualidade.avaliar_gate(result)
                if gate["bloqueia"] or any(f.get("blockingReason") for f in findings) or decision["resultado"].get("pendencias"):
                    raise ValueError()
            except Exception:
                raise ErroDocumento("A análise nativa e os gates de qualidade não autorizaram a aprovação.") from None
            snapshot = dict(reference, phase="approved", approved_revision=document.revision,
                approved_content_hash=document.content_hash, approved_engine_manifest_sha256=document.engine_build,
                draft_reference_sha256=document.institutional_snapshot_hash)
            raw = _snapshot_bytes(snapshot)
            evidence = {"schema": "gc-wordcraft-approval/v1", "document_id": document.id,
                "revision": document.revision, "content_hash": document.content_hash,
                "engine_manifest_sha256": document.engine_build, "coverage": "complete_textual_projection",
                "scope": "individual_revision_review", "official_emission": False,
                "evaluated_at": evaluated_at.isoformat(),
                "validator_version": validacao.versao_do_auditor(), "validator_findings": raw_findings,
                "quality": result, "gate": gate, "findings": findings, "decision": decision}
            if len(raw) > MAX_BYTES or len(_snapshot_bytes(evidence)) > MAX_BYTES:
                raise ErroDocumento("Evidência de aprovação excessiva.")
            params.update(p_sources=sources, p_snapshot="\\x" + raw.hex(),
                p_snapshot_sha256=hashlib.sha256(raw).hexdigest(), p_evidence=evidence)
        row = _one(_execute(db._cliente().rpc("documento_editor_aprovar", params)))
        expected = {"approval_id", "document_id", "revision", "content_hash", "operation_id",
                    "snapshot_sha256", "event_id", "replayed"}
        if (row.keys() != expected or (row["document_id"], row["revision"], row["content_hash"], row["operation_id"])
                != (vinculo.document_id, vinculo.revision, vinculo.content_hash, vinculo.operation_id)
                or type(row["replayed"]) is not bool
                or (params["p_snapshot_sha256"] is not None and row["snapshot_sha256"] != params["p_snapshot_sha256"])):
            raise ErroDocumento("Recibo de aprovação divergente.")
        _uuid(row["approval_id"])
        _uuid(row["event_id"])
        _hash(row["snapshot_sha256"])
        return Aprovacao(row["approval_id"], row["document_id"], row["revision"], row["content_hash"],
            row["operation_id"], row["snapshot_sha256"], row["event_id"], row["replayed"])

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
                        or mode not in {"initial", "reconciled", "rebuilt_missing_index", "rebuilt_build", "operational_patch"}):
                    raise ValueError()
                if engine_build == self._native["manifest_sha256"]:
                    blocos.validar_indice(index, payload, **self._native)
            except Exception:
                raise ErroDocumento("Índice documental divergente.") from None
        document = Documento(head["id"], head["processo_id"], head["tipo"], revision,
                         digest, head["status"] if revision == head["revision"] else "historico",
                         payload, engine_build, provenance, index, mode,
                         row.get("restored_from_revision"), institutional, row.get("institutional_snapshot_sha256"))
        if head["status"] == "aprovado":
            document = replace(document, approval=self._approval(user, document))
        return document

    def _approval(self, user, document):
        rows = _execute(user.table("governanca_aprovacoes")
            .select("id,aprovador,native_operation_id,native_revision,native_content_hash,native_snapshot,native_snapshot_sha256,native_evidence")
            .eq("entidade_tipo", "documento_editor").eq("entidade_id", document.id).eq("native_revision", document.revision).limit(1))
        if not rows:
            # A legacy status is not proof of a native approval. No backfill.
            return None
        row = _one(rows)
        try:
            encoded = row["native_snapshot"]
            if not isinstance(encoded, str) or not encoded.startswith("\\x") or len(encoded)>2*MAX_BYTES+2:
                raise ValueError()
            raw = bytes.fromhex(encoded[2:])
            snapshot = json.loads(raw, object_pairs_hook=blocos._objeto_fechado)
            expected = dict(document.institutional_snapshot or {}, phase="approved",
                approved_revision=document.revision, approved_content_hash=document.content_hash,
                approved_engine_manifest_sha256=document.engine_build,
                draft_reference_sha256=document.institutional_snapshot_hash)
            if (snapshot != expected or hashlib.sha256(raw).hexdigest() != row["native_snapshot_sha256"]
                    or row["native_revision"] != document.revision or row["native_content_hash"] != document.content_hash):
                raise ValueError()
            _uuid(row["id"])
            _uuid(row["aprovador"])
            _uuid(row["native_operation_id"])
            evidence = row["native_evidence"]
            if (not isinstance(evidence, dict) or evidence.get("schema") != "gc-wordcraft-approval/v1"
                    or (evidence.get("document_id"), evidence.get("revision"), evidence.get("content_hash"), evidence.get("engine_manifest_sha256"))
                    != (document.id, document.revision, document.content_hash, document.engine_build)
                    or evidence.get("official_emission") is not False or evidence.get("scope") != "individual_revision_review"
                    or evidence.get("gate", {}).get("bloqueia") is not False):
                raise ValueError()
            event = _one(_execute(user.table("governanca_eventos").select("id,ator,payload")
                .eq("entidade_tipo", "aprovacao").eq("entidade_id", row["id"])
                .eq("tipo_evento", "aprovacao_registrada").limit(1)))
            _uuid(event["id"])
            if (event["ator"] != row["aprovador"] or event["payload"].get("document_id") != document.id
                    or event["payload"].get("revision") != document.revision
                    or event["payload"].get("content_hash") != document.content_hash
                    or event["payload"].get("operation_id") != row["native_operation_id"]
                    or event["payload"].get("institutional_snapshot_sha256") != row["native_snapshot_sha256"]):
                raise ValueError()
            return Aprovacao(row["id"], document.id, document.revision, document.content_hash,
                row["native_operation_id"], row["native_snapshot_sha256"], event["id"], True,
                institutional_snapshot=snapshot, quality=evidence.get("quality"))
        except (ValueError, TypeError, KeyError, AttributeError, UnicodeError, RecursionError):
            raise ErroDocumento("Prova de aprovação nativa divergente.") from None

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

    def empacotar_aprovados(self, processo_id: str, *, tipos: tuple[str, ...],
                            formato: str) -> PacoteArtefatos:
        """ZIP auditável composto somente por revisões nativas aprovadas."""
        _uuid(processo_id)
        if (formato not in {"docx", "pdf"} or not tipos or len(tipos) > 32
                or len(set(tipos)) != len(tipos)
                or any(not isinstance(tipo, str)
                       or re.fullmatch(r"[a-z][a-z0-9_]{0,31}", tipo) is None
                       for tipo in tipos)):
            raise ErroDocumento("Pedido de pacote documental inválido.")
        by_type = {document.tipo: document for document in self.listar_processo(processo_id)}
        if set(by_type) != set(tipos):
            raise ErroDocumento("O conjunto nativo não corresponde ao pacote solicitado.")
        artifacts, entries = [], []
        for tipo in tipos:
            document = by_type[tipo]
            if document.status not in {"aprovado", "emitido"} or document.approval is None:
                raise ErroDocumento("O pacote contém revisão sem aprovação nativa.")
            artifact = self.exportar(document.id, expected_revision=document.revision,
                                     content_hash=document.content_hash, formato=formato)
            artifacts.append((tipo, artifact))
            entries.append({"tipo": tipo, "document_id": document.id,
                "revision": document.revision, "source_sha256": document.content_hash,
                "approval_id": document.approval.id,
                "approval_snapshot_sha256": document.approval.institutional_snapshot_hash,
                "artifact_sha256": artifact.content_hash,
                "engine_manifest_sha256": artifact.engine_build,
                "file": f"{tipo}-r{document.revision}.{formato}"})
        manifest = {"schema": "gc-wordcraft-artifact-package/v1",
                    "processo_id": processo_id, "formato": formato,
                    "official_emission": False, "documents": entries}
        manifest_bytes = json.dumps(manifest, ensure_ascii=False, sort_keys=True,
                                   separators=(",", ":")).encode("utf-8")
        output = io.BytesIO()
        with ZipFile(output, "w", ZIP_DEFLATED) as archive:
            for tipo, artifact in artifacts:
                info = ZipInfo(f"{tipo}-r{artifact.revision}.{formato}",
                               date_time=(1980, 1, 1, 0, 0, 0))
                info.compress_type = ZIP_DEFLATED
                archive.writestr(info, artifact.payload)
            info = ZipInfo("manifest.json", date_time=(1980, 1, 1, 0, 0, 0))
            info.compress_type = ZIP_DEFLATED
            archive.writestr(info, manifest_bytes)
        payload = output.getvalue()
        if len(payload) > MAX_BYTES * 8:
            raise ErroDocumento("Pacote documental excede o limite autorizado.")
        return PacoteArtefatos(processo_id, formato,
            hashlib.sha256(payload).hexdigest(), manifest, payload)

    def emitir_aprovados(self, processo_id: str, *, tipos: tuple[str, ...],
                         operation_id: str) -> Emissao:
        """Persiste os dois pacotes e cruza o limite oficial em uma RPC CAS."""
        _uuid(processo_id)
        _uuid(operation_id)
        docx = self.empacotar_aprovados(processo_id, tipos=tipos, formato="docx")
        pdf = self.empacotar_aprovados(processo_id, tipos=tipos, formato="pdf")
        docx_entries = {entry["tipo"]: entry for entry in docx.manifest["documents"]}
        pdf_entries = {entry["tipo"]: entry for entry in pdf.manifest["documents"]}
        documents = []
        for tipo in tipos:
            first, second = docx_entries.get(tipo), pdf_entries.get(tipo)
            common = ("document_id", "revision", "source_sha256", "approval_id",
                      "approval_snapshot_sha256", "engine_manifest_sha256")
            if first is None or second is None or any(first[key] != second[key] for key in common):
                raise ConflitoDocumento("As exportações não partiram da mesma revisão aprovada.")
            documents.append({"tipo": tipo, "document_id": first["document_id"],
                "revision": first["revision"], "source_sha256": first["source_sha256"],
                "approval_id": first["approval_id"],
                "approval_snapshot_sha256": first["approval_snapshot_sha256"],
                "engine_manifest_sha256": first["engine_manifest_sha256"],
                "docx_sha256": first["artifact_sha256"],
                "pdf_sha256": second["artifact_sha256"]})
        manifest = {"schema": "gc-wordcraft-official-emission/v1",
            "official_emission": True, "processo_id": processo_id,
            "engine_manifest_sha256": self._native["manifest_sha256"],
            "documents": documents,
            "packages": {"docx": {"sha256": docx.content_hash, "bytes": len(docx.payload)},
                         "pdf": {"sha256": pdf.content_hash, "bytes": len(pdf.payload)}}}
        _, claims = self._session()
        response = _execute(db._cliente().rpc("documento_editor_emitir", {
            "p_process": processo_id, "p_operation": operation_id,
            "p_engine_manifest_sha256": self._native["manifest_sha256"],
            "p_documents": documents, "p_manifest": manifest,
            "p_docx": "\\x" + docx.payload.hex(), "p_docx_sha256": docx.content_hash,
            "p_pdf": "\\x" + pdf.payload.hex(), "p_pdf_sha256": pdf.content_hash,
            "p_claims": claims}))
        expected = {"emission_id", "processo_id", "operation_id", "docx_sha256",
                    "pdf_sha256", "event_id", "replayed"}
        if (not isinstance(response, dict) or response.keys() != expected
                or (response["processo_id"], response["operation_id"],
                    response["docx_sha256"], response["pdf_sha256"])
                != (processo_id, operation_id, docx.content_hash, pdf.content_hash)
                or type(response["replayed"]) is not bool):
            raise ErroDocumento("Recibo de emissão nativa divergente.")
        try:
            _uuid(response["emission_id"])
            _uuid(response["event_id"])
        except (ValueError, TypeError):
            raise ErroDocumento("Identidade da emissão nativa divergente.") from None
        return Emissao(response["emission_id"], processo_id, operation_id,
            docx.content_hash, pdf.content_hash, response["event_id"],
            response["replayed"], manifest, docx, pdf)

    def emissao_atual(self, processo_id: str) -> Emissao | None:
        """Reabre o snapshot oficial persistido sem reexportar o documento."""
        _uuid(processo_id)
        user, _ = self._session()
        rows = _execute(user.table("documentos_editor_emissoes")
            .select("id,processo_id,operation_id,engine_manifest_sha256,manifest,"
                    "docx_package,docx_sha256,pdf_package,pdf_sha256,criado_em")
            .eq("processo_id", processo_id).order("criado_em", desc=True).limit(1))
        if not rows:
            return None
        if not isinstance(rows, list) or len(rows) > 1 or not isinstance(rows[0], dict):
            raise ErroDocumento("Histórico de emissão nativa ambíguo.")
        row = rows[0]
        try:
            _uuid(row["id"]); _uuid(row["operation_id"])
            manifest = row["manifest"]
            if (row["processo_id"] != processo_id
                    or manifest["schema"] != "gc-wordcraft-official-emission/v1"
                    or manifest["official_emission"] is not True
                    or manifest["processo_id"] != processo_id
                    or manifest["engine_manifest_sha256"] != row["engine_manifest_sha256"]):
                raise ValueError()
            payloads = {}
            for fmt in ("docx", "pdf"):
                encoded, digest = row[fmt + "_package"], row[fmt + "_sha256"]
                if not isinstance(encoded, str) or not encoded.startswith("\\x"):
                    raise ValueError()
                payload = bytes.fromhex(encoded[2:])
                if (not payload or hashlib.sha256(payload).hexdigest() != digest
                        or manifest["packages"][fmt] != {"sha256": digest, "bytes": len(payload)}):
                    raise ValueError()
                payloads[fmt] = PacoteArtefatos(processo_id, fmt, digest, manifest, payload)
        except (KeyError, TypeError, ValueError):
            raise ErroDocumento("Snapshot de emissão nativa divergente.") from None
        events = _execute(user.table("governanca_eventos").select("id,ator,payload")
            .eq("tipo_evento", "publicacao_registrada").eq("entidade_tipo", "publicacao")
            .eq("entidade_id", row["id"]).limit(2))
        if not isinstance(events, list) or len(events) != 1:
            raise ErroDocumento("Trilha da emissão nativa divergente.")
        event = events[0]
        try:
            _uuid(event["id"])
            if (event["payload"].get("operation_id") != row["operation_id"]
                    or event["payload"].get("official_emission") is not True):
                raise ValueError()
        except (KeyError, TypeError, ValueError):
            raise ErroDocumento("Evento da emissão nativa divergente.") from None
        return Emissao(row["id"], processo_id, row["operation_id"], row["docx_sha256"],
            row["pdf_sha256"], event["id"], True, manifest, payloads["docx"], payloads["pdf"])
