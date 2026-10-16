from pathlib import Path
from types import SimpleNamespace
from uuid import NAMESPACE_URL, uuid5

from src.documentos_editor import AcessoNegado
from src.ui import wordcraft_operacional as ui


class Session(dict):
    pass


def test_importacao_legada_e_idempotente_e_derivada_do_processo():
    process = "11111111-1111-1111-1111-111111111111"
    expected = str(uuid5(NAMESPACE_URL, "govconnect-document:" + process + ":tr"))
    operation = str(uuid5(NAMESPACE_URL,
        "govconnect-wordcraft-import:" + process + ":tr"))
    calls = []

    class Service:
        def abrir(self, document_id):
            calls.append(("abrir", document_id))
            raise AcessoNegado("indisponível")
        def importar_legado(self, **kwargs):
            calls.append(("importar", kwargs))
            return "documento"

    assert ui._abrir(Service(), process, "tr") == "documento"
    assert calls == [("abrir", expected), ("importar", {
        "processo_id": process, "tipo": "tr", "operation_id": operation,
        "formato": "markdown"})]


def test_owner_e_estavel_e_recusa_troca_de_build(monkeypatch):
    session = Session()
    monkeypatch.setattr(ui.st, "session_state", session)
    created = []
    monkeypatch.setattr(ui, "DocumentoService", lambda **kw: created.append(kw) or object())
    base = SimpleNamespace(node=Path("C:/node.exe"), bundle=Path("C:/static/wordcraft"),
                           manifest_sha256="a" * 64)
    first = ui._owner(base)
    assert ui._owner(base) is first and len(created) == 1
    changed = SimpleNamespace(node=base.node, bundle=base.bundle,
                              manifest_sha256="b" * 64)
    try:
        ui._owner(changed)
    except Exception as error:
        assert type(error).__name__ == "ErroRuntime"
    else:
        raise AssertionError("troca de build deveria ser recusada")


def test_runtime_invalido_falha_fechado_sem_montar_editor(monkeypatch):
    messages = []
    monkeypatch.setattr(ui.st, "session_state", Session())
    monkeypatch.setattr(ui, "carregar", lambda: (_ for _ in ()).throw(
        ui.ErroRuntime("runtime recusado")))
    monkeypatch.setattr(ui.st, "error", lambda value: messages.append(("error", value)))
    monkeypatch.setattr(ui.st, "info", lambda value: messages.append(("info", value)))
    monkeypatch.setattr(ui, "render_editor", lambda *a, **k: (_ for _ in ()).throw(
        AssertionError("editor não pode montar")))
    ui.render("tr", {"etapa": 3, "sigla": "TR"})
    assert messages[0] == ("error", "runtime recusado")
    assert "não é exibido junto" in messages[1][1]


def test_sincronizacao_reidrata_so_aprovacao_nativa_com_projecao(monkeypatch):
    approved = SimpleNamespace(id="doc-a", tipo="dfd", status="aprovado",
                               approval=SimpleNamespace(id="approval-a"))
    draft = SimpleNamespace(id="doc-b", tipo="etp", status="rascunho",
                            approval=None)
    service = SimpleNamespace(
        listar_processo=lambda process: (approved, draft),
        texto_aprovado=lambda document_id: ("dfd", "Texto nativo aprovado"),
    )
    session = Session(processo_id="11111111-1111-1111-1111-111111111111")
    monkeypatch.setattr(ui.st, "session_state", session)
    monkeypatch.setattr(ui, "carregar", lambda: object())
    monkeypatch.setattr(ui, "_owner", lambda runtime: service)
    assert ui.sincronizar() is True
    assert session["_documentos_editor_aprovados"] == {"dfd"}
    assert session["_documentos_editor_contexto"] == {"dfd": "Texto nativo aprovado"}
    assert session["_documentos_editor_aprovacoes"]["dfd"].id == "approval-a"


def test_falha_de_sincronizacao_nao_reaproveita_aprovacao_anterior(monkeypatch):
    session = Session(processo_id="11111111-1111-1111-1111-111111111111",
        _documentos_editor_aprovados={"dfd"},
        _documentos_editor_contexto={"dfd": "stale"})
    monkeypatch.setattr(ui.st, "session_state", session)
    monkeypatch.setattr(ui, "carregar", lambda: (_ for _ in ()).throw(
        ui.ErroRuntime("runtime recusado")))
    assert ui.sincronizar() is False
    assert session["_documentos_editor_aprovados"] == set()
    assert session["_documentos_editor_contexto"] == {}


def test_steps_troca_a_superficie_inteira_antes_do_editor_legado():
    source = (Path(__file__).parents[1] / "src/ui/steps.py").read_text(encoding="utf-8")
    start = source.index("if wordcraft_runtime.ativo():")
    rich = source.index('if db.flag_ativa("editor_rico"):', start)
    segment = source[start:rich]
    assert "render_wordcraft(doc_key, meta)" in segment
    assert "return" in segment


def test_app_separa_emissao_nativa_da_tela_legada():
    source = (Path(__file__).parents[1] / "app.py").read_text(encoding="utf-8")
    assert "wordcraft_operacional.sincronizar()" in source
    assert "wordcraft_operacional.render_sucesso()" in source
    assert "state.aprovacoes_efetivas()" in source


def test_tela_nativa_empacota_pelo_owner_e_nao_pelo_exportador_legado():
    source = (Path(__file__).parents[1] / "src/ui/wordcraft_operacional.py").read_text(encoding="utf-8")
    success = source[source.index("def render_sucesso") :]
    assert "service.empacotar_aprovados(" in success
    assert "package_sources == current_sources" in success
    assert "export.gerar_zip" not in success


def test_emissao_oficial_exige_confirmacao_e_reabre_snapshot_persistido():
    source = (Path(__file__).parents[1] / "src/ui/wordcraft_operacional.py").read_text(encoding="utf-8")
    success = source[source.index("def render_sucesso") :]
    assert "service.emissao_atual(" in success
    assert 'st.checkbox("Confirmo a emissão' in success
    assert "disabled=not confirmed" in success
    assert "service.emitir_aprovados(" in success
    assert "st.rerun()" in success


def test_checkpoint_de_patch_confirma_lote_antes_do_ack_do_canvas(monkeypatch):
    operation = "22222222-2222-2222-2222-222222222222"
    checkpoint = SimpleNamespace(request_id=operation, expected_revision=3,
                                 content_hash="b" * 64, content=b"patched")
    preparation = SimpleNamespace(operation_id=operation)
    confirmed = []
    class Bridge:
        instance_id = "33333333-3333-3333-3333-333333333333"
        document_id = "44444444-4444-4444-4444-444444444444"
        origin = "http://127.0.0.1:8501"
        def receber_lote(self, batch, **kwargs): return checkpoint
        def confirmar_checkpoint(self, **kwargs): confirmed.append(kwargs)
        def canvas_bloqueado(self): return None
        def falha_controle(self): return None
    receipt = SimpleNamespace(request_id=operation, revision=4, content_hash="b" * 64,
                              engine_build="c" * 64, validation_provenance="server_manifest_sha256",
                              index="index", index_mode="operational_patch", restored_from_revision=None)
    batch_receipt = SimpleNamespace(operation_id=operation, audit_id="audit", documentos=(receipt,),
                                    canvas_confirmado=True)
    class Service:
        def confirmar_patches(self, prep, *, checkpoints):
            assert prep is preparation and checkpoints == {"tr": checkpoint}
            return batch_receipt
        def checkpoint(self, *args): raise AssertionError("não pode usar checkpoint comum")
    session = Session()
    session[ui._chave("tr", "bridge")] = Bridge()
    session[ui._chave("tr", "preparation")] = preparation
    session[ui._chave("tr", "document")] = SimpleNamespace(revision=3)
    session["wordcraft_" + session[ui._chave("tr", "bridge")].instance_id] = {"edit": {"events": []}}
    monkeypatch.setattr(ui.st, "session_state", session)
    monkeypatch.setattr(ui, "replace", lambda current, **values: SimpleNamespace(**{**vars(current), **values}))
    ui._receber("tr", Service())
    assert confirmed == [{"request_id": operation, "revision": 4, "content_hash": "b" * 64}]
    assert session[ui._chave("tr", "preparation")] is None
    assert session[ui._chave("tr", "patch_receipt")] is batch_receipt
    assert session[ui._chave("tr", "document")].payload == b"patched"
    assert session[ui._chave("tr", "history")][-1]["canvas_confirmado"] is True


def test_trilha_d_captura_selecao_prepara_diff_e_nao_aceita_lote_multicanvas():
    source = (Path(__file__).parents[1] / "src/ui/wordcraft_operacional.py").read_text(encoding="utf-8")
    render = source[source.index("def render(doc_key") : source.index("def render_sucesso")]
    assert "bridge.solicitar_selecao(" in render
    assert "bridge.selecao_atual()" in render
    assert "propositor_selecao(" in render
    assert "propositor_govbot_selecao(" in render
    assert "Gerar proposta com GovBot" in render
    assert "service.preparar_patches(" in render
    assert "len(preparation.resultados) == len(preparation.comandos) == 1" in render
    assert "Aplicar proposta no canvas" in render and "Rejeitar proposta" in render
