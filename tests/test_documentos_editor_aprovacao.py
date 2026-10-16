"""Owner/state contract; native engine and HTTP transport are explicit stubs.

Projection, validation, knowledge, consistency and quality run real Python code.
Real transaction/RLS/concurrency proofs live in the SQL companion module.
"""
import copy
from dataclasses import replace
import hashlib
import json
from types import SimpleNamespace
from uuid import uuid4

import pytest

from src import documentos_editor as owner
from src import perfis
from tests.test_documentos_editor import Query, setup
from tests.test_documentos_editor_institucional import institutional


@pytest.fixture
def approval(institutional, monkeypatch):
    service, state, _ = institutional
    body = []
    for clause in perfis.PERFIS["dfd"]["clausulas"]:
        title = f"{clause['n']}. {clause['titulo']}"
        body.append({"kind": "para", "text": title, "props": {"style": "GovDocsClausula"},
            "runs": [{"len": len(title.encode())}]})
        for ordinal in range(5):
            text = (f"A unidade sintética documenta a necessidade administrativa {ordinal} com responsabilidade "
                "definida e critérios objetivos de atendimento ao interesse público. " * 15).strip()
            body.append({"kind": "para", "text": text, "runs": [{"len": len(text.encode())}]})
    payload = json.dumps({"schema": owner.SCHEMA, "document": {"body": body, "parts": {}},
        "media": {}, "passthrough": {}}, ensure_ascii=False).encode()
    document = service.criar(processo_id=state["process"]["id"], tipo="dfd", payload=payload, operation_id=str(uuid4()))
    fields = {"procedimento.srp": False, "procedimento.dedicacao_mao_de_obra": False,
        "procedimento.execucao_continuada": False, "objeto.natureza": "BENS", "objeto.categoria": "OUTROS",
        "contratacao.garantia_exigida": False, "contratacao.amostra_exigida": False}
    facts = [{"id": str(uuid4()), "path": path, "status": "confirmado", "valor": value, "versao": 1, "hash": "x"}
        for path,value in fields.items()]
    sources = {"processo": state["process"], **state["catalogs"], "fatos_canonicos": [
        {"id": str(uuid4()), "processo_id": document.processo_id, "path": "fato_de_teste",
         "status": "confirmado", "valor": "evidência sintética confirmada", "versao": 1, "hash": "x"}] + facts,
        "regras_conhecimento": [], "fontes_conhecimento": [], "config_app": [],
        "governanca_artefatos": [], "governanca_versoes": []}
    state.update(sources=sources, approval_calls=[], source_calls=[], projection_calls=[])
    old_server = owner.db._cliente()
    original_projection = owner.blocos.projetar_documento

    def project(*args, **kwargs):
        result = original_projection(*args, **kwargs)
        state["projection_calls"].append(result)
        return result

    class Server:
        def rpc(self, name, params):
            if name == "documento_editor_fontes_aprovacao":
                state["source_calls"].append(params)
                return Query(copy.deepcopy(sources))
            if name != "documento_editor_aprovar": return old_server.rpc(name, params)
            state["approval_calls"].append(params)
            row = dict(approval_id=str(uuid4()), document_id=params["p_document"], revision=params["p_revision"],
                content_hash=params["p_content_hash"], operation_id=params["p_operation"],
                snapshot_sha256=params["p_snapshot_sha256"] or state["approved_hash"], event_id=str(uuid4()),
                replayed=params["p_snapshot"] is None)
            if state.get("bad_receipt"): row["content_hash"] = "b" * 64
            state["head"]["status"] = "aprovado"
            state["approved_hash"] = row["snapshot_sha256"]
            return Query([row])
    monkeypatch.setattr(owner.db, "_cliente", lambda: Server())
    monkeypatch.setattr(owner.blocos, "projetar_documento", project)
    binding = owner.VinculoAprovacao(document.id, 1, document.content_hash, str(uuid4()))
    return service, state, document, binding


def test_owner_uses_real_projection_and_canonical_gates_on_backend_sources(approval):
    service, state, document, binding = approval
    receipt = service.aprovar(binding)
    call = state["approval_calls"][0]
    assert receipt.status == "aprovado" and receipt.revision == 1
    assert state["source_calls"] == [{"p_document": document.id, "p_claims": state["context"]}]
    assert state["projection_calls"][0].content_hash == document.content_hash
    assert call["p_sources"] == state["sources"] and call["p_claims"] is state["context"]
    evidence = call["p_evidence"]
    assert evidence["quality"]["config_versao"] == "quality-config@1"
    assert evidence["quality"]["score"] >= 75 and evidence["gate"]["bloqueia"] is False
    assert any(f["path"] == "fato_de_teste" for f in evidence["decision"]["fatos_versoes"])
    assert any(r["chave"].startswith("base.") for r in evidence["decision"]["regras_versoes"])
    assert evidence["official_emission"] is False and evidence["scope"] == "individual_revision_review"
    snapshot = json.loads(bytes.fromhex(call["p_snapshot"][2:]))
    assert snapshot["phase"] == "approved" and snapshot["approved_content_hash"] == document.content_hash
    assert snapshot["draft_reference_sha256"] == document.institutional_snapshot_hash
    assert snapshot["signatories"][0]["nome_snapshot"] == "Ana Sintética"
    assert state["process"]["documentos"] == {"dfd": "Texto original **sintético**"}


@pytest.mark.parametrize("change", ["unconfirmed", "missing_facts", "registry", "ineligible", "coverage", "build", "historical", "stale"])
def test_owner_blocks_missing_or_stale_proofs_before_approval_rpc(approval, monkeypatch, change):
    service, state, document, binding = approval
    if change == "unconfirmed": state["sources"]["fatos_canonicos"][0]["status"] = "extraido"
    if change == "missing_facts": state["sources"]["fatos_canonicos"] = []
    if change == "registry": state["sources"]["secretarias"][0]["cabecalho"] = "CHANGED"
    if change == "ineligible": state["sources"]["servidores"][0]["ativo"] = False
    if change == "coverage":
        original = owner.blocos.projetar_documento
        monkeypatch.setattr(owner.blocos, "projetar_documento", lambda *a, **k: replace(original(*a, **k), areas_nao_cobertas=("objeto",)))
    if change == "build": state["history"][1]["engine_build_sha256"] = "b" * 64
    if change == "historical":
        state["history"][1].update(institutional_snapshot=None, institutional_snapshot_sha256=None)
    if change == "stale": binding = replace(binding, revision=2)
    with pytest.raises(owner.ErroDocumento): service.aprovar(binding)
    assert state["approval_calls"] == []


def test_retry_uses_recorded_act_without_recomputing_history_after_registry_change(approval):
    service, state, _, binding = approval
    original = service.aprovar(binding)
    state["sources"]["servidores"][0]["ativo"] = False
    retried = service.aprovar(binding)
    assert retried.replayed and retried.institutional_snapshot_hash == original.institutional_snapshot_hash
    assert len(state["source_calls"]) == len(state["projection_calls"]) == 1
    assert state["approval_calls"][1]["p_sources"] is None


def test_reopening_approved_revision_reads_immutable_approval_and_institutional_proof(approval, monkeypatch):
    service, state, document, binding = approval
    receipt = service.aprovar(binding)
    params = state["approval_calls"][0]
    row = dict(id=receipt.id, aprovador=state["context"]["sub"], native_operation_id=binding.operation_id,
        native_revision=1, native_content_hash=binding.content_hash, native_snapshot=params["p_snapshot"],
        native_snapshot_sha256=receipt.institutional_snapshot_hash, native_evidence=params["p_evidence"])
    event = dict(id=receipt.event_id, ator=row["aprovador"], payload={"document_id": document.id,
        "revision": 1, "content_hash": binding.content_hash, "operation_id": binding.operation_id,
        "institutional_snapshot_sha256": receipt.institutional_snapshot_hash})
    old_user = owner.db.cliente_do_usuario()

    class User:
        def rpc(self, name, params): return old_user.rpc(name, params)
        def table(self, name):
            if name == "governanca_aprovacoes": return Query([row])
            if name == "governanca_eventos": return Query([event])
            return old_user.table(name)
    monkeypatch.setattr(owner.db, "cliente_do_usuario", lambda: User())
    state["sources"]["servidores"][0]["nome"] = "LATER NAME"
    state["sources"]["servidores"][0]["ativo"] = False
    reopened = service.abrir(document.id)
    assert reopened.approval.id == receipt.id and reopened.approval.content_hash == document.content_hash
    assert reopened.approval.institutional_snapshot["phase"] == "approved"
    assert reopened.approval.institutional_snapshot["signatories"][0]["nome_snapshot"] == "Ana Sintética"
    assert reopened.approval.quality["score"] >= 75 and reopened.institutional_snapshot["phase"] == "draft_reference"
    row["native_snapshot"] = "\\x00"
    with pytest.raises(owner.ErroDocumento, match="aprovação nativa"): service.abrir(document.id)


def test_old_approved_status_does_not_invent_a_bound_native_approval(approval):
    service, state, document, _ = approval
    state["head"]["status"] = "aprovado"
    reopened = service.abrir(document.id)
    assert reopened.approval is None and reopened.status == "aprovado"
    assert state["approval_calls"] == []


def test_owner_never_acknowledges_a_mismatched_approval_receipt(approval):
    service, state, _, binding = approval
    state["bad_receipt"] = True
    with pytest.raises(owner.ErroDocumento, match="Recibo"): service.aprovar(binding)


@pytest.mark.parametrize("cause", ["critical", "pending"])
def test_current_backend_knowledge_blocks_even_when_projection_is_valid(approval, cause):
    from src import governanca
    service, state, _, binding = approval
    condition = {"field": "fato_de_teste" if cause == "critical" else "fato_ausente",
        "operator": "EQ", "value": "evidência sintética confirmada"}
    state["sources"]["regras_conhecimento"] = [governanca.nova_regra("qa.approval.block", "municipio", condition,
        [{"type": "BLOQUEAR_EMISSAO", "motivo": "Regra backend de prova"}], status="PUBLISHED")]
    with pytest.raises(owner.ErroDocumento, match="gates"): service.aprovar(binding)
    assert state["approval_calls"] == []


def test_state_native_act_preserves_markdown_stage_and_legacy_approvals(approval, monkeypatch):
    from src import operacao_documento, state as workflow
    from src.wordcraft_protocol import Ponte
    service, state, document, binding = approval
    session = {"documentos": {"dfd": "OLD MARKDOWN"}, "aprovados": {"etp"}, "etapa": 2,
        "processo_id": document.processo_id, "_documentos_editor_vinculos": {"dfd": binding}}
    messages = []
    monkeypatch.setattr(workflow, "st", SimpleNamespace(session_state=session, error=messages.append, info=messages.append))
    monkeypatch.setattr(workflow.db, "em_manutencao", lambda: False)
    monkeypatch.setattr(operacao_documento, "ocupada", lambda s: False)
    monkeypatch.setattr(workflow, "autosalvar", lambda: pytest.fail("native act must not autosave legacy fields"))
    bridge = Ponte("http://localhost:8884", str(uuid4()), str(uuid4()), document.id,
        "n" * 48, revision=1, content_hash=document.content_hash)
    bridge.state = "ready"  # Backend accepted document.loaded in the renderer.
    receipt = workflow.aprovar_e_avancar("dfd", "BROWSER MARKDOWN", vinculo_nativo=binding,
        documento_service=service, ponte_nativa=bridge)
    assert receipt.status == "aprovado" and session["_aprovacoes_documentais"]["dfd"] is receipt
    assert session["documentos"] == {"dfd": "OLD MARKDOWN"} and session["aprovados"] == {"etp"} and session["etapa"] == 2
    assert "emissão" in messages[0]


@pytest.mark.parametrize("bridge_state", ["opening", "dirty", "saving", "error", "conflict"])
def test_state_blocks_an_unconfirmed_dirty_or_conflicting_bridge(approval, monkeypatch, bridge_state):
    from src import operacao_documento, state as workflow
    from src.wordcraft_protocol import Ponte
    service, state, document, binding = approval
    session = {"processo_id": document.processo_id, "documentos": {"dfd": "OLD"}, "etapa": 1, "aprovados": set()}
    errors = []
    monkeypatch.setattr(workflow, "st", SimpleNamespace(session_state=session, error=errors.append))
    monkeypatch.setattr(workflow.db, "em_manutencao", lambda: False)
    monkeypatch.setattr(operacao_documento, "ocupada", lambda s: False)
    bridge = Ponte("http://localhost:8884", str(uuid4()), str(uuid4()), document.id,
        "n" * 48, revision=1, content_hash=document.content_hash)
    bridge.state = bridge_state
    assert workflow.aprovar_e_avancar("dfd", "FORGED", vinculo_nativo=binding,
        documento_service=service, ponte_nativa=bridge) is None
    assert errors and not state["approval_calls"] and session["etapa"] == 1 and not session["aprovados"]


def test_visual_policy_reuses_published_backend_version_and_source_revocation(approval):
    service, state, _, binding = approval
    artifact_id = str(uuid4())
    state["sources"]["config_app"] = [{"chave": "flag_visual_policy_builder", "valor": "true"}]
    state["sources"]["governanca_artefatos"] = [{"id": artifact_id, "chave_estavel": "qa.visual.approval",
        "tenant_id": state["head"]["tenant_id"], "secretaria_id": None}]
    state["sources"]["governanca_versoes"] = [{"artefato_id": artifact_id, "versao": 2, "status": "PUBLISHED",
        "payload": {"condicao": {"field": "fato_de_teste", "operator": "EXISTS"},
            "acoes": [{"type": "BLOQUEAR_EMISSAO", "motivo": "Política vigente"}], "fontes": ["fonte-qa"]}}]
    with pytest.raises(owner.ErroDocumento, match="gates"): service.aprovar(binding)
    state["sources"]["fontes_conhecimento"] = [{"id": str(uuid4()), "rotulo": "fonte-qa", "vigente": False}]
    service.aprovar(binding)
    decision = state["approval_calls"][0]["p_evidence"]["decision"]
    assert any(r["chave"] == "qa.visual.approval" and "revogada" in r["motivo"]
        for r in decision["resultado"]["regras_ignoradas"])


def test_native_text_view_does_not_fake_a_financial_table_quality_pass(approval):
    service, state, _, binding = approval
    state["sources"]["processo"]["dados"]["itens"] = [{"codigo": "1001", "descricao": "Objeto sintético",
        "unidade": "UN", "quantidade": 2, "valor_unitario": 10}]
    # Native text coverage does not supply the table format consumed by the
    # existing financial validator. It must block until a structured adapter
    # can feed that validator, instead of pretending that no table was needed.
    with pytest.raises(owner.ErroDocumento, match="gates"): service.aprovar(binding)
    assert state["projection_calls"][0].apto_analise and state["approval_calls"] == []


def test_state_refuses_unbound_approval_when_native_document_is_registered(approval, monkeypatch):
    from src import operacao_documento, state as workflow
    _, state, document, binding = approval
    session = {"documentos": {"dfd": "OLD"}, "aprovados": set(), "etapa": 1,
        "processo_id": document.processo_id, "_documentos_editor_vinculos": {"dfd": binding}}
    errors = []
    monkeypatch.setattr(workflow, "st", SimpleNamespace(session_state=session, error=errors.append))
    monkeypatch.setattr(workflow.db, "em_manutencao", lambda: False)
    monkeypatch.setattr(operacao_documento, "ocupada", lambda s: False)
    assert workflow.aprovar_e_avancar("dfd", "FORGED") is None
    assert errors and state["approval_calls"] == [] and session["etapa"] == 1 and not session["aprovados"]
