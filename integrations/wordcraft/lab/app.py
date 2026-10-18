"""Synthetic local slice only; never mounted in the operational product."""
from collections.abc import Mapping
from dataclasses import replace
import hashlib
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
from src.wordcraft_capacidades import (Capacidade, CorrecaoContextual,
                                       ErroCapacidade, propositor)

CONFIG = json.loads(os.environ["GOVDOCS_WORDCRAFT_LAB"])
st.set_page_config(layout="wide")
st.title("WordCraft local — revisão, importação e restauração")
st.info("Somente corpus sintético e PostgreSQL/PostgREST em loopback. JWT do ensaio verificado pelo PostgREST; GoTrue e produção não são usados.")
if db._segredo("SUPABASE_URL") != os.environ["SUPABASE_URL"]:
    st.error("Laboratório recusado: o cliente não está no endereço isolado.")
    st.stop()
identity = CONFIG["identity"]
if not st.session_state.get("qa_authenticated"):
    auth.entrar({**{k: identity[k] for k in ("id", "auth_user_id", "tenant_id", "secretaria_id", "papel")},
                 "nome": "Operador sintético", "_token": os.environ["GOVDOCS_WORDCRAFT_QA_ACCESS_TOKEN"]})
    st.session_state.qa_authenticated = True
owner_config = (CONFIG["node"], CONFIG["lab"], CONFIG["manifest_sha256"])
if "qa_native_owner" not in st.session_state:
    st.session_state.qa_native_owner = DocumentoService(node=Path(CONFIG["node"]),
        bundle=Path(CONFIG["lab"]) / "static/wordcraft", manifest_sha256=CONFIG["manifest_sha256"])
    st.session_state.qa_native_owner_config = owner_config
if st.session_state.qa_native_owner_config != owner_config:
    st.error("O build do owner mudou. Preserve o rascunho e reinicie a sessão do laboratório.")
    st.stop()
service = st.session_state.qa_native_owner
cases = list(identity["processes"])
requested = st.query_params.get("case", cases[0])
if requested not in cases:
    requested = cases[0]
selected = st.selectbox("Documento sintético", cases, index=cases.index(requested))
sources = ("checkpoint", "docx", "markdown")
requested_source = st.query_params.get("source", sources[0])
source = st.selectbox("Origem inicial sintética", sources,
    index=sources.index(requested_source) if requested_source in sources else 0)
discard = st.checkbox("Confirmo descartar eventual rascunho local ao trocar/reabrir")
open_clicked = st.button("Abrir revisão persistida do documento selecionado")


def mount_document(document, message):
    st.session_state.document = document
    st.session_state.bridge = Ponte(CONFIG["origin"], str(uuid4()), str(uuid4()), document.id,
                                    secrets.token_urlsafe(48), revision=document.revision, content_hash=document.content_hash)
    st.session_state.backend_message = message


def open_document(case, source_format):
    process_id = identity["processes"][case]
    doc_type = {"checkpoint": "dfd", "docx": "etp", "markdown": "tr"}[source_format]
    doc_id = str(uuid5(NAMESPACE_URL, "govconnect-document:" + process_id + ":" + doc_type))
    try:
        document = service.abrir(doc_id)
    except AcessoNegado:
        operation = str(uuid5(NAMESPACE_URL, "wordcraft-qa-initial:" + process_id + ":" + source_format))
        if source_format == "checkpoint":
            content = Path(CONFIG["checkpoints"][case]).read_bytes()
            document = service.criar(processo_id=process_id, tipo=doc_type, payload=content, operation_id=operation)
        else:
            original = None
            if source_format == "docx":
                original = (REPO / "tests/fixtures/wordcraft" / (case + ".docx")).read_bytes()
            document = service.importar_legado(processo_id=process_id, tipo=doc_type,
                operation_id=operation, formato=source_format, original_docx=original)
    mount_document(document, "Revisão aberta do armazenamento privado.")
    st.query_params["case"] = case
    st.query_params["source"] = source_format


try:
    if "document" not in st.session_state:
        open_document(requested, source)
    elif open_clicked:
        # Backend dirty state can lag the canvas polling loop. Every remount
        # needs explicit consent until a native clean/flush handshake exists.
        if discard:
            open_document(selected, source)
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
            preparation = st.session_state.get("qa_patch_preparation")
            patch_checkpoint = (preparation is not None
                                and checkpoint.request_id == preparation.operation_id)
            if patch_checkpoint:
                batch_receipt = service.confirmar_patches(
                    preparation, checkpoints={document.tipo: checkpoint})
                if len(batch_receipt.documentos) != 1:
                    raise ErroDocumento("Recibo G4 não corresponde ao canvas único.")
                receipt = batch_receipt.documentos[0]
                st.session_state.qa_patch_receipt = batch_receipt
                st.session_state.qa_patch_preparation = None
            else:
                receipt = service.checkpoint(bridge.document_id, checkpoint)
            bridge.confirmar_checkpoint(request_id=receipt.request_id, revision=receipt.revision,
                                         content_hash=receipt.content_hash)
            st.session_state.document = replace(st.session_state.document, revision=receipt.revision,
                                                 content_hash=receipt.content_hash, payload=checkpoint.content,
                                                 engine_build=receipt.engine_build,
                                                 validation_provenance=receipt.validation_provenance,
                                                 index=receipt.index, index_mode=receipt.index_mode,
                                                 restored_from_revision=receipt.restored_from_revision)
            st.session_state.backend_message = (
                "Patch G4 confirmado atomicamente no PostgreSQL; ACK correlacionado à operação."
                if patch_checkpoint else
                "Commit confirmado no PostgreSQL; ACK correlacionado à operação.")
        elif bridge.canvas_bloqueado() is not None:
            st.session_state.backend_message = "Canvas bloqueado e hash confirmado para análise; nenhum ato foi aprovado."
        elif bridge.falha_controle() is not None:
            failure = bridge.falha_controle()
            st.session_state.backend_message = (
                "Patch G4 recusado pelo canvas sem alterar a revisão: " + failure["reason"] + "."
                if failure["reason"] in {"patch_refused", "target_mismatch"} else
                "Bloqueio recusado; preserve o rascunho e aguarde a gravação antes de uma nova análise.")
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
st.caption("Índice derivado: " + document.index_mode + " · " + str(len(document.index.blocos) if document.index else 0) + " blocos")
st.caption(st.session_state.backend_message)
from src.ui.wordcraft_editor import render_editor
render_editor(bridge, document.payload,
              module_url=CONFIG["module_url"],
              wasm_url=CONFIG["wasm_url"], on_edit_change=receive)

# The same presentation component is used by the operational host later. This
# lab supplies only synthetic owner data and never grants the panel persistence.
from src.ui.wordcraft_painel import modelo as modelo_painel, renderizar as renderizar_painel
history_panel = []
if st.session_state.get("qa_history", (None,))[0] == document.id:
    _, historical_revision, historical_hash = st.session_state.qa_history
    history_panel.append({"revision": historical_revision, "content_hash": historical_hash})
renderizar_painel(modelo_painel(
    preparacao=st.session_state.get("qa_context_preparation"),
    auditoria_atual=st.session_state.get("qa_context_audit"),
    evidencias=st.session_state.get("qa_context_evidence", ()),
    template=st.session_state.get("qa_context_template"),
    montagem=st.session_state.get("qa_context_assembly"),
    historico=history_panel,
))

# QA do percurso G4 real: usa exatamente o owner, compilador, motor nativo,
# transação e ACK do produto. O laboratório só fornece corpus/ator sintéticos.
if st.button("Carregar auditoria contextual G4",
             disabled=bridge.state not in {"ready", "saved"}
             or bridge.controle_pendente() is not None):
    try:
        st.session_state.qa_context_audit = service.auditoria_atual(document.processo_id)
        st.rerun()
    except ErroDocumento as error:
        st.error(str(error))
audit = st.session_state.get("qa_context_audit")
findings = ([item for item in audit["report"]["findings"]
             if item.get("documentId") == document.tipo
             and item.get("autoCorrectable") is True] if audit else [])
if audit is not None:
    st.caption("Auditoria vinculada ao bundle " + audit["report"]["bundleHash"]
               + " · achados autocorrigíveis deste documento: " + str(len(findings)))
    finding_counts = {}
    for item in audit["report"]["findings"]:
        if item.get("autoCorrectable") is True:
            key = str(item.get("documentId") or "sem-documento")
            finding_counts[key] = finding_counts.get(key, 0) + 1
    st.caption("Achados autocorrigíveis no pacote por documento: "
               + (json.dumps(finding_counts, sort_keys=True, ensure_ascii=False)
                  if finding_counts else "nenhum"))
if findings and st.session_state.get("qa_patch_preparation") is None:
    labels = {item["findingId"]: item["findingId"] + " · "
              + str(item.get("descricao") or "") for item in findings}
    finding_id = st.selectbox("Achado G4 para corrigir", tuple(labels),
                              format_func=labels.get)
    replacement = st.text_area("Parágrafo corrigido para o ensaio G4",
        value="Texto sintético revisado pelo aplicador único G4, sem alterar dados materiais.",
        max_chars=64 * 1024)
    reason = st.text_input("Justificativa sintética G4",
                           value="Correção sintética autorizada para prova end-to-end.",
                           max_chars=500)
    if st.button("Preparar patch G4 e diff", disabled=not replacement.strip()):
        selected_finding = next(item for item in findings
                                if item["findingId"] == finding_id)
        operation = str(uuid5(NAMESPACE_URL, "wordcraft-lab-g4:"
            + document.id + ":" + document.content_hash + ":" + finding_id
            + ":" + replacement + ":" + reason))
        correction = CorrecaoContextual(Capacidade.AUDITORIA, finding_id,
            replacement, reason, tuple(selected_finding.get("sourceIds") or ()))
        try:
            st.session_state.qa_patch_preparation = service.preparar_patches(
                document.processo_id, operation_id=operation,
                propor_plano=propositor(correction))
            st.rerun()
        except (ErroDocumento, ErroCapacidade) as error:
            st.error(str(error))
preparation = st.session_state.get("qa_patch_preparation")
if preparation is not None:
    results = tuple(r for r in preparation.resultados
                    if r.fonte.doc_key == document.tipo)
    commands = tuple(c for c in preparation.comandos
                     if c.fonte.doc_key == document.tipo)
    source_ok = (len(preparation.resultados) == len(preparation.comandos) == 1
                 and len(results) == len(commands) == 1
                 and results[0].fonte.document_id == document.id
                 and results[0].fonte.revision == document.revision
                 and results[0].fonte.content_hash == document.content_hash)
    st.warning("Patch preparado sem gravação. Confirme para aplicar os bytes exatos no canvas.")
    apply_col, reject_col = st.columns(2)
    if apply_col.button("Aplicar patch G4 no canvas", type="primary",
                        disabled=not source_ok or bridge.state not in {"ready", "saved"}
                        or bridge.controle_pendente() is not None):
        bridge.solicitar_patch(preparation.operation_id,
            plano=commands[0].plano_nativo(), target_hash=results[0].content_hash)
        st.rerun()
    if reject_col.button("Rejeitar patch G4"):
        service.descartar_patches(preparation)
        st.session_state.qa_patch_preparation = None
        st.session_state.backend_message = "Patch G4 rejeitado sem alterar o documento."
        st.rerun()
receipt = st.session_state.get("qa_patch_receipt")
if receipt is not None:
    st.success("Recibo G4 persistido: operação " + receipt.operation_id
               + " · auditoria " + receipt.audit_id
               + " · canvas confirmado: " + str(receipt.canvas_confirmado))

# Fixed position after the editor preserves the component mount across reruns.
if st.button("Bloquear esta revisão para análise", disabled=bridge.state not in {"ready", "saved"} or bridge.controle_pendente() is not None):
    bridge.solicitar_bloqueio(str(uuid4()))
    st.session_state.backend_message = "Bloqueio solicitado. Aguardando confirmação do canvas exato."
    st.rerun()
proof = bridge.canvas_bloqueado()
if proof is not None:
    st.caption("Canvas confirmado: operação " + proof["command_id"] + " · geração " + proof["generation"])
if st.button("Liberar revisão para continuar editando", disabled=proof is None):
    bridge.liberar_bloqueio(proof["command_id"])
    st.session_state.backend_message = "Liberação solicitada para a mesma operação."
    st.rerun()
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

st.caption("Histórico sintético: restauração grava uma nova revisão e preserva a anterior.")
source_revision = st.number_input("Revisão histórica", min_value=1, max_value=document.revision, value=1, step=1)
if st.button("Conferir revisão histórica"):
    historical = service.abrir_revisao(document.id, int(source_revision))
    st.session_state.qa_history = (historical.id, historical.revision, historical.content_hash)
if st.session_state.get("qa_history", (None,))[0] == document.id:
    _, number, digest = st.session_state.qa_history
    st.caption("Histórico: revisão " + str(number) + " · SHA-256 " + digest)
if st.button("Restaurar como nova revisão", disabled=not discard or bridge.state not in {"ready", "saved"}):
    try:
        receipt = service.restaurar(document.id, source_revision=int(source_revision),
            expected_revision=document.revision, operation_id=str(uuid4()))
        restored = service.abrir(document.id)
        mount_document(restored, "Restauração confirmada: nova revisão " + str(receipt.revision) + "; histórico preservado.")
        st.rerun()
    except ErroDocumento as error:
        st.error("Restauração recusada: " + type(error).__name__)
if st.button("Conferir original importado"):
    try:
        original = service.original(document.id, 1)
        assert hashlib.sha256(original.payload).hexdigest() == original.content_hash
        st.session_state.qa_original = (document.id, original.formato, original.content_hash, len(original.payload))
    except ErroDocumento:
        st.session_state.qa_original = (document.id, "ausente", "não registrado", 0)
if st.session_state.get("qa_original", (None,))[0] == document.id:
    _, fmt, digest, size = st.session_state.qa_original
    st.caption("Original: " + fmt + " · " + str(size) + " bytes · SHA-256 " + digest)
