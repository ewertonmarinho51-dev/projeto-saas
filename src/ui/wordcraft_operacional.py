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
from .wordcraft_editor import render_editor
from .wordcraft_painel import modelo as modelo_painel, renderizar as renderizar_painel


def _chave(doc_key: str, sufixo: str) -> str:
    return f"_wordcraft_{doc_key}_{sufixo}"


def _owner(runtime: Runtime) -> DocumentoService:
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
            if document.status != "aprovado" or document.approval is None:
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


def _receber(doc_key: str, service: DocumentoService) -> None:
    bridge = st.session_state[_chave(doc_key, "bridge")]
    result = st.session_state.get("wordcraft_" + bridge.instance_id)
    batch = result.get("edit") if isinstance(result, Mapping) else getattr(result, "edit", None)
    if batch is None:
        return
    checkpoint = None
    try:
        checkpoint = bridge.receber_lote(batch, origin=bridge.origin, source_ok=True)
        if checkpoint is not None:
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
            st.session_state[_chave(doc_key, "message")] = "Revisão nativa salva e confirmada."
        elif bridge.canvas_bloqueado() is not None:
            st.session_state[_chave(doc_key, "message")] = "Canvas exato bloqueado para revisão."
        elif bridge.falha_controle() is not None:
            st.session_state[_chave(doc_key, "message")] = "O canvas recusou o bloqueio; a revisão foi preservada."
    except Exception as error:
        if checkpoint is not None:
            bridge.falhar_checkpoint(request_id=checkpoint.request_id,
                                     conflict=isinstance(error, ConflitoDocumento))
        st.session_state[_chave(doc_key, "message")] = \
            "Operação nativa recusada: " + type(error).__name__


def render(doc_key: str, meta: dict) -> None:
    """Renderiza exclusivamente WordCraft; nunca monta o editor antigo junto."""
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
    render_editor(bridge, document.payload, module_url=runtime.module_url,
                  wasm_url=runtime.wasm_url,
                  on_edit_change=lambda: _receber(doc_key, service))
    renderizar_painel(modelo_painel(
        preparacao=st.session_state.get(_chave(doc_key, "preparation")),
        evidencias=st.session_state.get(_chave(doc_key, "evidence"), ()),
        template=st.session_state.get(_chave(doc_key, "template")),
        montagem=st.session_state.get(_chave(doc_key, "assembly")),
        historico=st.session_state.get(_chave(doc_key, "history"), ()),
    ))
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
            if doc.status == "aprovado" and doc.approval is not None}
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
