"""Synthetic local slice only; never mounted in the operational product."""
from collections.abc import Mapping
from dataclasses import replace
import json
import os
from pathlib import Path
import secrets
import sys
from uuid import uuid4, uuid5, NAMESPACE_URL

REPO = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO))
import streamlit as st
from src import auth, db
from src.documentos_editor import DocumentoService, AcessoNegado, ConflitoDocumento, ErroDocumento
from src.wordcraft_protocol import Ponte

CONFIG = json.loads(os.environ["GOVDOCS_WORDCRAFT_LAB"])
st.set_page_config(layout="wide")
st.title("G1 local — edição com commit real")
st.info("Somente corpus sintético e PostgreSQL/PostgREST em loopback. JWT do ensaio verificado pelo PostgREST; GoTrue e produção não são usados.")
if db._segredo("SUPABASE_URL") != os.environ["SUPABASE_URL"]:
    st.error("Laboratório recusado: o cliente não está no endereço isolado.")
    st.stop()
identity = CONFIG["identity"]
if not st.session_state.get("qa_authenticated"):
    auth.entrar({**{k: identity[k] for k in ("id", "auth_user_id", "tenant_id", "secretaria_id", "papel")},
                 "nome": "Operador sintético", "_token": os.environ["GOVDOCS_WORDCRAFT_QA_ACCESS_TOKEN"]})
    st.session_state.qa_authenticated = True
service = DocumentoService(node=Path(CONFIG["node"]),
    bundle=Path(CONFIG["lab"]) / "static/wordcraft", manifest_sha256=CONFIG["manifest_sha256"])
cases = list(identity["processes"])
requested = st.query_params.get("case", cases[0])
if requested not in cases:
    requested = cases[0]
selected = st.selectbox("Documento sintético", cases, index=cases.index(requested))
discard = st.checkbox("Confirmo descartar eventual rascunho local ao trocar/reabrir")
open_clicked = st.button("Abrir revisão persistida do documento selecionado")


def open_document(case):
    process_id = identity["processes"][case]
    doc_id = str(uuid5(NAMESPACE_URL, "govconnect-document:" + process_id + ":dfd"))
    try:
        document = service.abrir(doc_id)
    except AcessoNegado:
        content = (Path(CONFIG["corpus"]) / case / "checkpoint.json").read_bytes()
        document = service.criar(processo_id=process_id, tipo="dfd", payload=content,
                                 operation_id=str(uuid5(NAMESPACE_URL, "wordcraft-qa-initial:" + process_id)))
    st.session_state.document = document
    st.session_state.bridge = Ponte(CONFIG["origin"], str(uuid4()), str(uuid4()), document.id,
                                    secrets.token_urlsafe(48), revision=document.revision, content_hash=document.content_hash)
    st.session_state.backend_message = "Revisão aberta do armazenamento privado."
    st.query_params["case"] = case


try:
    if "document" not in st.session_state:
        open_document(requested)
    elif open_clicked:
        # Backend dirty state can lag the canvas polling loop. Every remount
        # needs explicit consent until a native clean/flush handshake exists.
        if discard:
            open_document(selected)
        else:
            st.session_state.backend_message = "Rascunho preservado: confirme o descarte antes de reabrir."
except ErroDocumento:
    st.error("Não foi possível abrir a revisão. Confira a sessão do laboratório; credenciais sintéticas expiradas exigem reinício do runner, preservando o banco.")
    st.stop()


def receive():
    bridge = st.session_state.bridge
    result = st.session_state.get("wordcraft_" + bridge.instance_id)
    batch = result.get("edit") if isinstance(result, Mapping) else getattr(result, "edit", None)
    if batch is None:
        return
    checkpoint = None
    try:
        checkpoint = bridge.receber_lote(batch, origin=bridge.origin, source_ok=True)
        if checkpoint is not None:
            receipt = service.checkpoint(bridge.document_id, checkpoint)
            bridge.confirmar_checkpoint(request_id=receipt.request_id, revision=receipt.revision,
                                         content_hash=receipt.content_hash)
            st.session_state.document = replace(st.session_state.document, revision=receipt.revision,
                                                 content_hash=receipt.content_hash, payload=checkpoint.content,
                                                 engine_build=receipt.engine_build,
                                                 validation_provenance=receipt.validation_provenance)
            st.session_state.backend_message = "Commit confirmado no PostgreSQL; ACK correlacionado à operação."
    except Exception as error:
        if checkpoint is not None:
            bridge.falhar_checkpoint(request_id=checkpoint.request_id, conflict=isinstance(error, ConflitoDocumento))
        st.session_state.backend_message = "Operação recusada: " + type(error).__name__


bridge = st.session_state.bridge
document = st.session_state.document
st.button("Reexecutar montagem")
st.caption("Instância " + bridge.instance_id + " · estado backend: " + bridge.state)
st.caption("Revisão persistida: " + str(document.revision) + " · SHA-256 " + document.content_hash)
st.caption("Build da revisão: " + (document.engine_build or "não registrado") + " · " + document.validation_provenance)
st.caption(st.session_state.backend_message)
from src.ui.wordcraft_editor import render_editor
render_editor(bridge, document.payload,
              module_url=CONFIG["module_url"],
              wasm_url=CONFIG["wasm_url"], on_edit_change=receive)

# Fixed position after the editor preserves the component mount across reruns.
st.caption("Exportação de minuta sintética: exige a revisão confirmada no armazenamento.")
for fmt, mime in (("docx", "application/vnd.openxmlformats-officedocument.wordprocessingml.document"), ("pdf", "application/pdf")):
    if st.button("Preparar " + fmt.upper() + " da revisão persistida", disabled=bridge.state not in {"ready", "saved"}):
        try:
            artifact = service.exportar(document.id, expected_revision=document.revision,
                                         content_hash=document.content_hash, formato=fmt)
            st.session_state["qa_export_" + fmt] = artifact
        except Exception as error:
            st.error("Exportação recusada: " + type(error).__name__)
    artifact = st.session_state.get("qa_export_" + fmt)
    if artifact and artifact.document_id == document.id and artifact.revision == document.revision:
        st.caption("Fonte: revisão " + str(artifact.revision) + " · SHA-256 " + artifact.source_hash)
        st.download_button("Baixar minuta " + fmt.upper(), artifact.payload,
                           file_name=next(case for case, process in identity["processes"].items() if process == document.processo_id) + "-r" + str(artifact.revision) + "." + fmt,
                           mime=mime, on_click="ignore")
