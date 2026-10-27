"""Host operacional, protegido pela flag única e pelo runtime admitido.

Este módulo substitui a superfície de edição quando a flag está ligada. Ele
não cai silenciosamente no editor legado: falha de runtime, importação ou save
fica visível e preserva a fonte/revisão existentes.
"""
from __future__ import annotations

from collections.abc import Mapping
from dataclasses import replace
import secrets
from uuid import NAMESPACE_URL, uuid4, uuid5

import streamlit as st

from .. import state
from ..documentos_editor import (AcessoNegado, ConflitoDocumento,
                                 DocumentoService, ErroDocumento,
                                 VinculoAprovacao)
from ..wordcraft_protocol import Ponte
from ..wordcraft_runtime import ErroRuntime, Runtime, carregar
from .. import wordcraft_session
from ..wordcraft_capacidades import (Capacidade, CorrecaoContextual,
                                     ErroCapacidade, propositor,
                                     propositor_govbot_selecao,
                                     propositor_selecao)
from .wordcraft_editor import render_editor
from .wordcraft_painel import modelo as modelo_painel, renderizar as renderizar_painel


def _chave(doc_key: str, sufixo: str) -> str:
    return f"_wordcraft_{doc_key}_{sufixo}"


def _rascunho_legado_pendente(doc_key: str) -> bool:
    """Detecta texto local que ainda não foi incorporado ao documento canônico."""
    documents = st.session_state.get("documentos")
    canonical = documents.get(doc_key) if isinstance(documents, Mapping) else None
    pending = st.session_state.get("edicoes_pendentes")
    candidates = []
    if isinstance(pending, Mapping):
        candidates.append(pending.get(doc_key))
    candidates.append(st.session_state.get(f"editor_{doc_key}"))
    return any(isinstance(value, str) and value != canonical for value in candidates)


def _owner(runtime: Runtime) -> DocumentoService:
    wordcraft_session.bind(st.session_state)
    config = (str(runtime.node), str(runtime.bundle), runtime.manifest_sha256)
    current = st.session_state.get("_wordcraft_owner")
    if current is None:
        current = DocumentoService(node=runtime.node, bundle=runtime.bundle,
                                   manifest_sha256=runtime.manifest_sha256)
        st.session_state["_wordcraft_owner"] = current
        st.session_state["_wordcraft_owner_config"] = config
    elif st.session_state.get("_wordcraft_owner_config") != config:
        raise ErroRuntime("O build WordCraft mudou durante a sessão; recarregue de forma controlada.")
    return current


def sincronizar() -> bool:
    """Reidrata aprovações/contexto a partir dos heads nativos persistidos."""
    processo_id = st.session_state.get("processo_id")
    if not isinstance(processo_id, str):
        st.session_state["_documentos_editor_aprovados"] = set()
        st.session_state["_documentos_editor_contexto"] = {}
        return True
    try:
        service = _owner(carregar())
        approved, context, bindings = set(), {}, {}
        for document in service.listar_processo(processo_id):
            if document.status not in {"aprovado", "emitido"} or document.approval is None:
                continue
            key, text = service.texto_aprovado(document.id)
            approved.add(key)
            context[key] = text
            bindings[key] = document.approval
        st.session_state["_documentos_editor_aprovados"] = approved
        st.session_state["_documentos_editor_contexto"] = context
        st.session_state["_documentos_editor_aprovacoes"] = bindings
        st.session_state.pop("_wordcraft_sync_error", None)
        return True
    except (ErroRuntime, ErroDocumento) as error:
        st.session_state["_documentos_editor_aprovados"] = set()
        st.session_state["_documentos_editor_contexto"] = {}
        st.session_state["_wordcraft_sync_error"] = str(error)
        return False


def _abrir(service: DocumentoService, processo_id: str, doc_key: str):
    document_id = str(uuid5(NAMESPACE_URL,
                            "govconnect-document:" + processo_id + ":" + doc_key))
    try:
        return service.abrir(document_id)
    except AcessoNegado:
        operation_id = str(uuid5(NAMESPACE_URL,
            "govconnect-wordcraft-import:" + processo_id + ":" + doc_key))
        return service.importar_legado(processo_id=processo_id, tipo=doc_key,
                                       operation_id=operation_id, formato="markdown")


def _montar(doc_key: str, document, runtime: Runtime) -> None:
    st.session_state[_chave(doc_key, "document")] = document
    st.session_state[_chave(doc_key, "bridge")] = Ponte(
        runtime.origin, str(uuid4()), str(uuid4()), document.id,
        secrets.token_urlsafe(48), revision=document.revision,
        content_hash=document.content_hash)


def _revisoes_restauraveis(history, current_revision: int) -> tuple[int, ...]:
    """Return only persisted historical revisions eligible for a new CAS revision."""
    if type(current_revision) is not int or current_revision < 1:
        return ()
    revisions = set()
    for item in history if isinstance(history, (list, tuple)) else ():
        if (isinstance(item, Mapping) and item.get("kind") == "revision"
                and item.get("current") is False
                and type(item.get("revision")) is int
                and 1 <= item["revision"] < current_revision):
            revisions.add(item["revision"])
    return tuple(sorted(revisions, reverse=True))


def _restaurar_operacional(doc_key: str, service: DocumentoService, runtime: Runtime,
                           source_revision: int) -> None:
    """Create a persisted restore revision and remount the canvas from its new head."""
    document = st.session_state[_chave(doc_key, "document")]
    bridge = st.session_state[_chave(doc_key, "bridge")]
    if bridge.state not in {"ready", "saved"}:
        raise ErroDocumento("Salve ou descarte a edição local antes de restaurar.")
    operation_id = str(uuid5(NAMESPACE_URL, "govconnect-wordcraft-restore:"
        + document.id + ":" + str(document.revision) + ":" + str(source_revision)))
    receipt = service.restaurar(document.id, source_revision=source_revision,
        expected_revision=document.revision, operation_id=operation_id)
    try:
        restored = service.abrir(document.id)
    except Exception:
        st.session_state.pop(_chave(doc_key, "document"), None)
        st.session_state.pop(_chave(doc_key, "bridge"), None)
        raise
    if ((restored.revision, restored.content_hash)
            != (receipt.revision, receipt.content_hash)):
        st.session_state.pop(_chave(doc_key, "document"), None)
        st.session_state.pop(_chave(doc_key, "bridge"), None)
        raise ErroDocumento("Head restaurada diverge do recibo persistido.")
    _montar(doc_key, restored, runtime)
    for suffix in ("preparation", "audit", "legal_opinions", "legal_attendance",
                   "evidence", "citation_check", "structure", "template_preview", "history",
                   "patch_receipt", "approval"):
        st.session_state.pop(_chave(doc_key, suffix), None)
    st.session_state[_chave(doc_key, "message")] = (
        f"Revisão {source_revision} restaurada como nova revisão {receipt.revision}.")


def _aplicar_template_operacional(doc_key: str, service: DocumentoService,
                                  runtime: Runtime, processo_id: str,
                                  version_id: str) -> None:
    """Apply the effective template atomically and remount the persisted head."""
    document = st.session_state[_chave(doc_key, "document")]
    bridge = st.session_state[_chave(doc_key, "bridge")]
    if bridge.state not in {"ready", "saved"}:
        raise ErroDocumento("Salve ou descarte a edição local antes de aplicar o template.")
    operation_id = str(uuid5(NAMESPACE_URL, "govconnect-wordcraft-template:"
        + document.id + ":" + str(document.revision) + ":" + version_id))
    prepared = service.preparar_template(processo_id, doc_key, version_id, operation_id)
    receipt = service.confirmar_template(prepared)
    try:
        applied = service.abrir(document.id)
    except Exception:
        st.session_state.pop(_chave(doc_key, "document"), None)
        st.session_state.pop(_chave(doc_key, "bridge"), None)
        raise
    if ((applied.revision, applied.content_hash, applied.index_mode)
            != (receipt.revision, receipt.content_hash, "template_application")):
        st.session_state.pop(_chave(doc_key, "document"), None)
        st.session_state.pop(_chave(doc_key, "bridge"), None)
        raise ErroDocumento("Head após aplicação do template diverge do recibo persistido.")
    _montar(doc_key, applied, runtime)
    for suffix in ("preparation", "audit", "legal_opinions", "legal_attendance",
                   "evidence", "citation_check", "structure", "template_preview", "history",
                   "patch_receipt", "approval"):
        st.session_state.pop(_chave(doc_key, suffix), None)
    st.session_state[_chave(doc_key, "message")] = (
        f"Template governado aplicado como revisão nativa {receipt.revision}.")


def _receber(doc_key: str, service: DocumentoService) -> None:
    bridge = st.session_state[_chave(doc_key, "bridge")]
    result = st.session_state.get("wordcraft_" + bridge.instance_id)
    batch = result.get("edit") if isinstance(result, Mapping) else getattr(result, "edit", None)
    if batch is None:
        return
    sequence_before = bridge.sequence
    checkpoint = None
    try:
        checkpoint = bridge.receber_lote(batch, origin=bridge.origin, source_ok=True)
        if checkpoint is not None:
            preparation = st.session_state.get(_chave(doc_key, "preparation"))
            patch_checkpoint = (preparation is not None
                                and checkpoint.request_id == preparation.operation_id)
            if patch_checkpoint:
                batch_receipt = service.confirmar_patches(
                    preparation, checkpoints={doc_key: checkpoint})
                if len(batch_receipt.documentos) != 1:
                    raise ErroDocumento("Recibo do patch não corresponde ao canvas único.")
                receipt = batch_receipt.documentos[0]
                st.session_state[_chave(doc_key, "patch_receipt")] = batch_receipt
                st.session_state[_chave(doc_key, "preparation")] = None
                history = list(st.session_state.get(_chave(doc_key, "history"), ()))
                history.append({"kind": "receipt",
                                "operation_id": batch_receipt.operation_id,
                                "audit_id": batch_receipt.audit_id,
                                "revision": receipt.revision,
                                "content_hash": receipt.content_hash,
                                "canvas_confirmado": batch_receipt.canvas_confirmado})
                st.session_state[_chave(doc_key, "history")] = history[-20:]
            else:
                receipt = service.checkpoint(bridge.document_id, checkpoint)
            bridge.confirmar_checkpoint(request_id=receipt.request_id,
                revision=receipt.revision, content_hash=receipt.content_hash)
            current = st.session_state[_chave(doc_key, "document")]
            st.session_state[_chave(doc_key, "document")] = replace(current,
                revision=receipt.revision, content_hash=receipt.content_hash,
                payload=checkpoint.content, engine_build=receipt.engine_build,
                validation_provenance=receipt.validation_provenance,
                index=receipt.index, index_mode=receipt.index_mode,
                restored_from_revision=receipt.restored_from_revision)
            st.session_state.pop(_chave(doc_key, "audit"), None)
            st.session_state.pop(_chave(doc_key, "legal_opinions"), None)
            st.session_state.pop(_chave(doc_key, "legal_attendance"), None)
            st.session_state.pop(_chave(doc_key, "evidence"), None)
            st.session_state.pop(_chave(doc_key, "structure"), None)
            st.session_state.pop(_chave(doc_key, "template_preview"), None)
            st.session_state[_chave(doc_key, "message")] = (
                "Patch nativo aplicado, persistido e confirmado; Undo permanece no canvas."
                if patch_checkpoint else "Revisão nativa salva e confirmada.")
        elif bridge.canvas_bloqueado() is not None:
            st.session_state[_chave(doc_key, "message")] = "Canvas exato bloqueado para revisão."
        elif bridge.falha_controle() is not None:
            st.session_state[_chave(doc_key, "message")] = "O canvas recusou o bloqueio; a revisão foi preservada."
        # A component-v2 callback can finish after the current render already
        # sent its data payload.  Force one complete application rerun whenever
        # the bridge consumes new transport events so ``event_ack`` reaches the
        # browser before the outbox re-emits the accepted prefix.  Replayed
        # prefixes do not advance ``sequence`` and therefore cannot loop here.
        if bridge.sequence != sequence_before:
            st.rerun()
    except Exception as error:
        if checkpoint is not None:
            bridge.falhar_checkpoint(request_id=checkpoint.request_id,
                                     conflict=isinstance(error, ConflitoDocumento))
        st.session_state[_chave(doc_key, "message")] = \
            "Operação nativa recusada: " + type(error).__name__


def render(doc_key: str, meta: dict) -> None:
    """Renderiza exclusivamente WordCraft; nunca monta o editor antigo junto."""
    if _rascunho_legado_pendente(doc_key):
        st.error(
            "Existe uma edição não salva no editor legado. Desative temporariamente "
            "a flag WordCraft e salve ou descarte esse rascunho antes da migração."
        )
        st.info(
            "O rascunho continua preservado nesta sessão; nenhum documento nativo "
            "foi aberto ou importado."
        )
        return
    try:
        runtime = carregar()
        service = _owner(runtime)
        processo_id = st.session_state.get("processo_id")
        if not isinstance(processo_id, str):
            raise ErroDocumento("Processo persistido obrigatório para o editor nativo.")
        document = st.session_state.get(_chave(doc_key, "document"))
        if (document is None or document.processo_id != processo_id
                or document.tipo != doc_key):
            document = _abrir(service, processo_id, doc_key)
            _montar(doc_key, document, runtime)
        bridge = st.session_state[_chave(doc_key, "bridge")]
        document = st.session_state[_chave(doc_key, "document")]
    except (ErroRuntime, ErroDocumento) as error:
        st.error(str(error))
        st.info("O editor legado permanece preservado, mas não é exibido junto ao WordCraft.")
        return

    st.caption(f"Revisão nativa {document.revision} · SHA-256 {document.content_hash}")
    message = st.session_state.get(_chave(doc_key, "message"))
    if message:
        st.caption(message)
    # Components v2 may keep this run open until the browser publishes its next
    # state value.  Reserve the visual position now, but mount the canvas only
    # after the server-side controls have been rendered.  Otherwise a freeze
    # acknowledgement can update the bridge while the approval controls below
    # remain unreachable behind the pending component call.
    editor_slot = st.empty()
    preparation_key = _chave(doc_key, "preparation")
    audit_key = _chave(doc_key, "audit")
    opinions_key = _chave(doc_key, "legal_opinions")
    attendance_key = _chave(doc_key, "legal_attendance")
    evidence_key = _chave(doc_key, "evidence")
    citation_key = _chave(doc_key, "citation_check")
    structure_key = _chave(doc_key, "structure")
    template_preview_key = _chave(doc_key, "template_preview")
    history_key = _chave(doc_key, "history")
    current_audit = st.session_state.get(audit_key)
    if current_audit is not None:
        binding = current_audit.get("report", {}).get("sourceNative", {}).get(doc_key, {})
        if ((binding.get("documentId"), binding.get("revision"), binding.get("sourceHash"))
                != (document.id, document.revision, document.content_hash)):
            st.session_state.pop(audit_key, None)
    current_opinions = st.session_state.get(opinions_key)
    if current_opinions is not None:
        binding = current_opinions.get("sourceNative", {}).get(doc_key, {})
        if ((binding.get("documentId"), binding.get("revision"), binding.get("sourceHash"))
                != (document.id, document.revision, document.content_hash)):
            st.session_state.pop(opinions_key, None)
    current_evidence = st.session_state.get(evidence_key)
    if current_evidence is not None:
        binding = current_evidence.get("sourceNative", {}).get(doc_key, {})
        if ((binding.get("documentId"), binding.get("revision"), binding.get("sourceHash"))
                != (document.id, document.revision, document.content_hash)):
            st.session_state.pop(evidence_key, None)
    current_structure = st.session_state.get(structure_key)
    if current_structure is not None:
        binding = current_structure.get("sourceNative", {}).get(doc_key, {})
        if ((binding.get("documentId"), binding.get("revision"), binding.get("sourceHash"))
                != (document.id, document.revision, document.content_hash)):
            st.session_state.pop(structure_key, None)
            st.session_state.pop(template_preview_key, None)
    selection = bridge.selecao_atual()
    if st.session_state.get(preparation_key) is None:
        if st.button("Executar auditoria contextual", key=_chave(doc_key, "audit_button")):
            try:
                st.session_state[audit_key] = service.auditoria_atual(processo_id)
                st.rerun()
            except ErroDocumento as error:
                st.error(str(error))
        if st.button("Carregar pareceres jurídicos analisados",
                     key=_chave(doc_key, "legal_opinions_button")):
            try:
                st.session_state[opinions_key] = service.pareceres_atuais(processo_id)
                st.rerun()
            except ErroDocumento as error:
                st.error(str(error))
        if st.button("Carregar relatórios de atendimento jurídico",
                     key=_chave(doc_key, "legal_attendance_button")):
            try:
                st.session_state[attendance_key] = service.atendimentos_parecer(
                    processo_id)
                st.rerun()
            except ErroDocumento as error:
                st.error(str(error))
        if st.button("Carregar fontes factuais verificadas",
                     key=_chave(doc_key, "evidence_button")):
            try:
                st.session_state[evidence_key] = service.evidencias_atuais(processo_id)
                st.rerun()
            except ErroDocumento as error:
                st.error(str(error))
        evidence_panel = st.session_state.get(evidence_key)
        catalog_sources = ((evidence_panel or {}).get("fontesConhecimento") or [])
        if catalog_sources:
            source_labels = {item["sourceId"]: item["label"] for item in catalog_sources}
            source_id = st.selectbox("Fonte para conferir citação", tuple(source_labels),
                format_func=source_labels.get, key=_chave(doc_key, "citation_source"))
            citation = st.text_area("Citação literal a conferir", max_chars=4000,
                key=_chave(doc_key, "citation_text"))
            if st.button("Conferir citação na base RAG",
                         disabled=len(citation.strip()) < 16,
                         key=_chave(doc_key, "citation_button")):
                try:
                    st.session_state[citation_key] = service.verificar_citacao(
                        processo_id, source_id, citation)
                    st.rerun()
                except ErroDocumento as error:
                    st.error(str(error))
        if st.button("Carregar estrutura institucional e montagem",
                     key=_chave(doc_key, "structure_button")):
            try:
                st.session_state[structure_key] = service.estrutura_atual(
                    processo_id, doc_key)
                st.rerun()
            except ErroDocumento as error:
                st.error(str(error))
        template_catalog = ((st.session_state.get(structure_key) or {}).get(
            "templatesPublicados") or [])
        if template_catalog:
            template_labels = {item["versionId"]:
                f"{item['description'] or item['key']} · v{item['version']}"
                for item in template_catalog}
            template_versions = tuple(template_labels)
            effective_version = ((st.session_state.get(structure_key) or {}).get(
                "templateEfetivo") or {}).get("versionId")
            default_template = (template_versions.index(effective_version)
                if effective_version in template_versions else 0)
            template_version = st.selectbox("Template publicado para prévia",
                template_versions, index=default_template, format_func=template_labels.get,
                key=_chave(doc_key, "template_version"))
            if st.button("Gerar prévia determinística do template",
                         key=_chave(doc_key, "template_preview_button")):
                try:
                    st.session_state[template_preview_key] = service.previsualizar_template(
                        processo_id, doc_key, template_version)
                    st.rerun()
                except ErroDocumento as error:
                    st.error(str(error))
            preview = st.session_state.get(template_preview_key)
            can_apply = (template_version == effective_version
                and isinstance(preview, Mapping)
                and (preview.get("template") or {}).get("versionId") == template_version
                and not (preview.get("preview") or {}).get("pending"))
            with st.form(_chave(doc_key, "template_apply_form")):
                template_confirmed = st.checkbox(
                    "Confirmo a substituição do conteúdo pela prévia e a criação de uma nova revisão.",
                    key=_chave(doc_key, "template_apply_confirm"))
                template_submitted = st.form_submit_button(
                    "Aplicar template efetivo como nova revisão",
                    disabled=not can_apply or bridge.state not in {"ready", "saved"})
            if template_submitted:
                if not template_confirmed:
                    st.error("Confirme a substituição pelo template antes de aplicar.")
                else:
                    try:
                        _aplicar_template_operacional(doc_key, service, runtime,
                                                      processo_id, template_version)
                        st.rerun()
                    except ErroDocumento as error:
                        st.error(str(error))
        if st.button("Carregar histórico persistido",
                     key=_chave(doc_key, "history_button")):
            try:
                st.session_state[history_key] = service.historico_revisoes(
                    document.id)["revisions"]
                st.rerun()
            except ErroDocumento as error:
                st.error(str(error))
        restore_options = _revisoes_restauraveis(
            st.session_state.get(history_key), document.revision)
        if restore_options:
            with st.form(_chave(doc_key, "restore_form")):
                source_revision = st.selectbox("Revisão histórica para restaurar",
                    restore_options, key=_chave(doc_key, "restore_revision"))
                restore_confirmed = st.checkbox(
                    "Confirmo a criação de uma nova revisão com esse conteúdo.",
                    key=_chave(doc_key, "restore_confirm"))
                restore_submitted = st.form_submit_button("Restaurar como nova revisão",
                    disabled=bridge.state not in {"ready", "saved"})
            if restore_submitted:
                if not restore_confirmed:
                    st.error("Confirme a criação da revisão restaurada antes de continuar.")
                else:
                    try:
                        _restaurar_operacional(doc_key, service, runtime, source_revision)
                        st.rerun()
                    except ErroDocumento as error:
                        st.error(str(error))
        current_audit = st.session_state.get(audit_key)
        findings = ([item for item in current_audit["report"]["findings"]
                     if item.get("documentId") == doc_key] if current_audit else [])
        correctable = [item for item in findings if item.get("autoCorrectable") is True]
        if correctable:
            labels = {item["findingId"]: f"{item['findingId']} · {item.get('descricao','')}"
                      for item in correctable}
            finding_id = st.selectbox("Achado auditado para corrigir", tuple(labels),
                                      format_func=labels.get,
                                      key=_chave(doc_key, "audit_finding"))
            audit_replacement = st.text_area("Parágrafo corrigido conforme o achado",
                key=_chave(doc_key, "audit_replacement"), max_chars=64 * 1024)
            audit_reason = st.text_input("Justificativa da correção auditada",
                key=_chave(doc_key, "audit_reason"), max_chars=500)
            if st.button("Preparar correção auditada", disabled=not audit_replacement.strip(),
                         key=_chave(doc_key, "prepare_audit")):
                selected = next(item for item in correctable if item["findingId"] == finding_id)
                operation = str(uuid5(NAMESPACE_URL, "govconnect-wordcraft-audit:"
                    + processo_id + ":" + doc_key + ":" + document.content_hash + ":"
                    + finding_id + ":" + audit_replacement + ":" + audit_reason))
                correction = CorrecaoContextual(Capacidade.AUDITORIA, finding_id,
                    audit_replacement, audit_reason or "Correção da auditoria contextual.",
                    tuple(selected.get("sourceIds") or ()))
                try:
                    st.session_state[preparation_key] = service.preparar_patches(
                        processo_id, operation_id=operation,
                        propor_plano=propositor(correction))
                    st.rerun()
                except (ErroDocumento, ErroCapacidade) as error:
                    st.error(str(error))
        current_opinions = st.session_state.get(opinions_key)
        legal_findings = ([item for item in current_opinions["findings"]
                           if item.get("documentId") == doc_key
                           and item.get("autoCorrectable") is True]
                          if current_opinions else [])
        if legal_findings:
            legal_labels = {item["findingId"]:
                f"{item['findingId']} · {item.get('descricao', '')}"
                for item in legal_findings}
            legal_id = st.selectbox("Recomendação jurídica objetiva",
                tuple(legal_labels), format_func=legal_labels.get,
                key=_chave(doc_key, "legal_finding"))
            legal_selected = next(item for item in legal_findings
                                  if item["findingId"] == legal_id)
            st.caption("Recomendação do parecer: "
                       + str(legal_selected.get("resultadoEsperado") or ""))
            legal_replacement = st.text_area(
                "Parágrafo proposto para atendimento do parecer",
                key=_chave(doc_key, "legal_replacement"), max_chars=64 * 1024)
            if st.button("Preparar atendimento e diff",
                         disabled=not legal_replacement.strip(),
                         key=_chave(doc_key, "prepare_legal")):
                operation = str(uuid5(NAMESPACE_URL, "govconnect-wordcraft-legal:"
                    + processo_id + ":" + doc_key + ":" + document.content_hash + ":"
                    + legal_id + ":" + legal_replacement))
                correction = CorrecaoContextual(Capacidade.PARECER, legal_id,
                    legal_replacement,
                    str(legal_selected.get("resultadoEsperado") or
                        "Atendimento objetivo do parecer jurídico."),
                    tuple(legal_selected.get("sourceIds") or ()))
                try:
                    st.session_state[preparation_key] = service.preparar_parecer(
                        processo_id, operation_id=operation,
                        propor_plano=propositor(correction))
                    st.rerun()
                except (ErroDocumento, ErroCapacidade) as error:
                    st.error(str(error))
        if st.button("Usar seleção no GovBot", disabled=bridge.state not in {"ready", "saved"}
                     or bridge.controle_pendente() is not None,
                     key=_chave(doc_key, "capture_selection")):
            bridge.solicitar_selecao(str(uuid4()))
            st.rerun()
        if selection is not None:
            st.caption("Seleção vinculada à revisão atual. Para substituir, selecione o parágrafo inteiro.")
            st.code(selection["text"][:2000])
            request = st.text_input("Pedido ao GovBot", key=_chave(doc_key, "govbot_request"),
                                    max_chars=2000,
                                    placeholder="Ex.: melhore a clareza sem alterar dados materiais")
            if st.button("Gerar proposta com GovBot", disabled=not request.strip(),
                         key=_chave(doc_key, "prepare_govbot")):
                operation = str(uuid5(NAMESPACE_URL, "govconnect-wordcraft-govbot:"
                    + processo_id + ":" + doc_key + ":" + document.content_hash + ":"
                    + selection["command_id"] + ":" + request))
                try:
                    st.session_state[preparation_key] = service.preparar_patches(
                        processo_id, operation_id=operation,
                        propor_plano=propositor_govbot_selecao(doc_key=doc_key,
                            texto_selecionado=selection["text"], pedido=request))
                    st.rerun()
                except (ErroDocumento, ErroCapacidade) as error:
                    st.error(str(error))
            st.caption("Ou prepare uma substituição manual pelo mesmo validador canônico.")
            replacement = st.text_area("Texto proposto para o parágrafo",
                key=_chave(doc_key, "replacement"), max_chars=64 * 1024)
            reason = st.text_input("Motivo da alteração", key=_chave(doc_key, "patch_reason"),
                                   max_chars=500)
            if st.button("Preparar proposta e diff", disabled=not replacement.strip(),
                         key=_chave(doc_key, "prepare_patch")):
                operation = str(uuid5(NAMESPACE_URL, "govconnect-wordcraft-selection:"
                    + processo_id + ":" + doc_key + ":" + document.content_hash + ":"
                    + selection["command_id"] + ":" + replacement + ":" + reason))
                try:
                    st.session_state[preparation_key] = service.preparar_patches(
                        processo_id, operation_id=operation,
                        propor_plano=propositor_selecao(doc_key=doc_key,
                            texto_selecionado=selection["text"], novo_texto=replacement,
                            motivo=reason or "Alteração contextual solicitada pelo usuário."))
                    st.rerun()
                except (ErroDocumento, ErroCapacidade) as error:
                    st.error(str(error))
    renderizar_painel(modelo_painel(
        preparacao=st.session_state.get(preparation_key),
        auditoria_atual=st.session_state.get(audit_key),
        pareceres_atuais=st.session_state.get(opinions_key),
        atendimentos_parecer=st.session_state.get(attendance_key),
        evidencias=(st.session_state.get(evidence_key) or {}).get("evidencias", ()),
        fontes_conhecimento=(st.session_state.get(evidence_key) or {}).get(
            "fontesConhecimento", ()),
        verificacao_citacao=st.session_state.get(citation_key),
        template=({"publicados": (st.session_state.get(structure_key) or {}).get(
                      "templatesPublicados", []),
                   "efetivo": (st.session_state.get(structure_key) or {}).get(
                      "templateEfetivo"),
                   "bloqueio": (st.session_state.get(structure_key) or {}).get(
                      "templateBlockingReason"),
                   "previa": st.session_state.get(template_preview_key)}
                  if st.session_state.get(structure_key) else None),
        institucional=(st.session_state.get(structure_key) or {}).get("institucional"),
        montagem=(st.session_state.get(structure_key) or {}).get("montagem"),
        historico=st.session_state.get(history_key, ()),
    ))
    preparation = st.session_state.get(_chave(doc_key, "preparation"))
    if preparation is not None:
        results = tuple(r for r in preparation.resultados if r.fonte.doc_key == doc_key)
        commands = tuple(c for c in preparation.comandos if c.fonte.doc_key == doc_key)
        source_ok = (len(preparation.resultados) == len(preparation.comandos) == 1
                     and len(results) == len(commands) == 1
                     and results[0].fonte.document_id == document.id
                     and results[0].fonte.revision == document.revision
                     and results[0].fonte.content_hash == document.content_hash)
        st.warning("A proposta abaixo altera somente o bloco mostrado no diff e exige confirmação.")
        accept, reject = st.columns(2)
        if accept.button("Aplicar proposta no canvas", type="primary",
                         disabled=not source_ok or bridge.state not in {"ready", "saved"}
                         or bridge.controle_pendente() is not None,
                         key=_chave(doc_key, "apply_patch")):
            bridge.solicitar_patch(preparation.operation_id,
                plano=commands[0].plano_nativo(), target_hash=results[0].content_hash)
            st.rerun()
        if reject.button("Rejeitar proposta", key=_chave(doc_key, "reject_patch")):
            service.descartar_patches(preparation)
            st.session_state[_chave(doc_key, "preparation")] = None
            st.session_state[_chave(doc_key, "message")] = "Proposta rejeitada sem alterar o documento."
            st.rerun()
    proof = bridge.canvas_bloqueado()
    if proof is None:
        if st.button("Revisar e preparar aprovação", type="primary",
                     disabled=bridge.state not in {"ready", "saved"}
                     or bridge.controle_pendente() is not None,
                     key=_chave(doc_key, "freeze")):
            bridge.solicitar_bloqueio(str(uuid4()))
            st.rerun()
    else:
        st.caption("Canvas bloqueado na revisão e no hash exibidos acima.")
        liberar, aprovar = st.columns([1, 2])
        if liberar.button("Continuar editando", key=_chave(doc_key, "release")):
            bridge.liberar_bloqueio(proof["command_id"])
            st.rerun()
        if aprovar.button(f"Aprovar {meta['sigla']}", type="primary",
                          key=_chave(doc_key, "approve")):
            binding = VinculoAprovacao(document.id, document.revision,
                                       document.content_hash, proof["command_id"])
            receipt = state.aprovar_e_avancar(doc_key, "", vinculo_nativo=binding,
                documento_service=service, ponte_nativa=bridge)
            if receipt is not None:
                st.session_state[_chave(doc_key, "approval")] = receipt
                if sincronizar():
                    state.ir_para(meta["etapa"] + 1)

    with editor_slot:
        render_editor(bridge, document.payload, module_url=runtime.module_url,
                      wasm_url=runtime.wasm_url,
                      on_edit_change=lambda: _receber(doc_key, service))


def render_sucesso() -> None:
    """Emite somente heads nativos aprovados; nunca usa exportadores legados."""
    st.subheader("Emissão nativa dos documentos")
    if not sincronizar():
        st.error(st.session_state.get("_wordcraft_sync_error") or
                 "Não foi possível confirmar as fontes nativas.")
        return
    try:
        service = _owner(carregar())
        documents = {doc.tipo: doc for doc in service.listar_processo(
            st.session_state["processo_id"])
            if doc.status in {"aprovado", "emitido"} and doc.approval is not None}
    except (ErroRuntime, ErroDocumento) as error:
        st.error(str(error))
        return
    expected = set(state.sequencia())
    if set(documents) != expected:
        st.error("O conjunto aprovado não cobre exatamente a sequência documental atual.")
        return
    st.success("As revisões nativas aprovadas estão prontas para exportação individual.")
    st.markdown("**Pacote auditável das revisões aprovadas**")
    package_columns = st.columns(2)
    current_sources = {key: documents[key].content_hash for key in state.sequencia()}
    for column, fmt in zip(package_columns, ("docx", "pdf")):
        cache_key = "_wordcraft_package_" + fmt
        if column.button("Preparar ZIP " + fmt.upper(), key=cache_key + "_button"):
            try:
                st.session_state[cache_key] = service.empacotar_aprovados(
                    st.session_state["processo_id"], tipos=tuple(state.sequencia()),
                    formato=fmt)
            except ErroDocumento as error:
                st.error(str(error))
        package = st.session_state.get(cache_key)
        package_sources = ({entry.get("tipo"): entry.get("source_sha256")
                            for entry in package.manifest.get("documents", [])}
                           if package is not None else {})
        if package is not None and package_sources == current_sources:
            column.download_button("Baixar ZIP " + fmt.upper(), package.payload,
                file_name=f"processo-{st.session_state['processo_id']}-{fmt}.zip",
                mime="application/zip", key=cache_key + "_download", on_click="ignore")
    try:
        emission = service.emissao_atual(st.session_state["processo_id"])
    except ErroDocumento as error:
        st.error(str(error))
        return
    if emission is not None:
        st.success("Emissão oficial registrada e vinculada à trilha de governança.")
        st.caption(f"Emissão `{emission.id}` · evento `{emission.event_id}`")
        persisted_columns = st.columns(2)
        for column, package, fmt in ((persisted_columns[0], emission.docx, "docx"),
                                     (persisted_columns[1], emission.pdf, "pdf")):
            column.download_button("Baixar emissão " + fmt.upper(), package.payload,
                file_name=f"emissao-{emission.id}-{fmt}.zip", mime="application/zip",
                key="_wordcraft_official_" + fmt, on_click="ignore")
    else:
        st.warning("Registrar a emissão congela estes pacotes como snapshot oficial imutável.")
        confirmed = st.checkbox("Confirmo a emissão das revisões e hashes exibidos.",
                                key="_wordcraft_confirm_emission")
        if st.button("Registrar emissão oficial", type="primary", disabled=not confirmed,
                     key="_wordcraft_emit"):
            source_key = ":".join(current_sources[key] for key in state.sequencia())
            operation = str(uuid5(NAMESPACE_URL, "govconnect-wordcraft-emission:"
                + st.session_state["processo_id"] + ":" + source_key))
            try:
                service.emitir_aprovados(st.session_state["processo_id"],
                    tipos=tuple(state.sequencia()), operation_id=operation)
                st.rerun()
            except ErroDocumento as error:
                st.error(str(error))
    for key in state.sequencia():
        document = documents[key]
        st.markdown(f"**{key.upper()}** · revisão {document.revision} · `{document.content_hash}`")
        columns = st.columns(2)
        for column, fmt, mime in ((columns[0], "docx",
                "application/vnd.openxmlformats-officedocument.wordprocessingml.document"),
                (columns[1], "pdf", "application/pdf")):
            cache_key = _chave(key, "export_" + fmt)
            if column.button("Preparar " + fmt.upper(), key=cache_key + "_button"):
                try:
                    st.session_state[cache_key] = service.exportar(document.id,
                        expected_revision=document.revision,
                        content_hash=document.content_hash, formato=fmt)
                except ErroDocumento as error:
                    st.error(str(error))
            artifact = st.session_state.get(cache_key)
            if (artifact is not None and artifact.document_id == document.id
                    and artifact.revision == document.revision
                    and artifact.source_hash == document.content_hash):
                column.download_button("Baixar " + fmt.upper(), artifact.payload,
                    file_name=f"{key}-r{document.revision}.{fmt}", mime=mime,
                    key=cache_key + "_download", on_click="ignore")
