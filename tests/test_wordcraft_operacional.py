from pathlib import Path
from types import SimpleNamespace
from uuid import NAMESPACE_URL, uuid5

import pytest

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
    session = Session(usuario={"id": "u1", "tenant_id": "t1"}, tenant_id="t1")
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


def test_owner_revoga_estado_ao_trocar_identidade_diretamente(monkeypatch):
    session = Session(usuario={"id": "u1", "tenant_id": "t1"}, tenant_id="t1")
    monkeypatch.setattr(ui.st, "session_state", session)
    created = []
    monkeypatch.setattr(ui, "DocumentoService", lambda **kw: created.append(kw) or object())
    runtime = SimpleNamespace(node=Path("C:/node.exe"), bundle=Path("C:/static/wordcraft"),
                              manifest_sha256="a" * 64)
    first = ui._owner(runtime)
    session[ui._chave("tr", "document")] = b"private checkpoint"
    session["wordcraft_11111111-1111-1111-1111-111111111111"] = {"edit": "private"}

    session["usuario"] = {"id": "u2", "tenant_id": "t2"}
    session["tenant_id"] = "t2"
    second = ui._owner(runtime)

    assert second is not first and len(created) == 2
    assert ui._chave("tr", "document") not in session
    assert "wordcraft_11111111-1111-1111-1111-111111111111" not in session


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


def test_rascunho_legado_pendente_compara_editor_e_bucket_com_documento_canonico(monkeypatch):
    session = Session(documentos={"tr": "Texto salvo", "etp": "ETP salvo"})
    monkeypatch.setattr(ui.st, "session_state", session)
    assert ui._rascunho_legado_pendente("tr") is False

    session["edicoes_pendentes"] = {"etp": "Outro documento", "tr": "Texto salvo"}
    session["editor_tr"] = "Texto salvo"
    assert ui._rascunho_legado_pendente("tr") is False

    session["edicoes_pendentes"]["tr"] = "Texto ainda não salvo"
    assert ui._rascunho_legado_pendente("tr") is True

    session["edicoes_pendentes"].pop("tr")
    session["editor_tr"] = ""
    assert ui._rascunho_legado_pendente("tr") is True


def test_rascunho_legado_impede_runtime_importacao_e_canvas(monkeypatch):
    session = Session(documentos={"tr": "Texto salvo"},
                      edicoes_pendentes={"tr": "Texto local"},
                      editor_tr="Texto local")
    messages = []
    monkeypatch.setattr(ui.st, "session_state", session)
    monkeypatch.setattr(ui.st, "error", lambda value: messages.append(("error", value)))
    monkeypatch.setattr(ui.st, "info", lambda value: messages.append(("info", value)))
    monkeypatch.setattr(ui, "carregar", lambda: (_ for _ in ()).throw(
        AssertionError("runtime não pode ser carregado")))
    monkeypatch.setattr(ui, "_abrir", lambda *a, **k: (_ for _ in ()).throw(
        AssertionError("documento não pode ser aberto ou importado")))
    monkeypatch.setattr(ui, "render_editor", lambda *a, **k: (_ for _ in ()).throw(
        AssertionError("canvas não pode montar")))

    ui.render("tr", {"etapa": 3, "sigla": "TR"})

    assert session["edicoes_pendentes"]["tr"] == "Texto local"
    assert session["editor_tr"] == "Texto local"
    assert "edição não salva" in messages[0][1]
    assert "nenhum documento nativo" in messages[1][1]


def test_preflight_fatos_sincroniza_exibe_confirma_e_so_entao_libera_aprovacao(monkeypatch):
    processo = "11111111-1111-1111-1111-111111111111"
    session = Session(dados={"objeto": "Aquisição sintética"},
                      usuario={"id": "22222222-2222-2222-2222-222222222222"})
    state = {"facts": []}
    reruns, messages, calls = [], [], []
    confirm_key = "wordcraft_confirmar_fatos:" + processo
    buttons = {confirm_key: False}
    monkeypatch.setattr(ui.st, "session_state", session)
    monkeypatch.setattr(ui.st, "button", lambda label, **kw: buttons.get(kw.get("key"), False))
    monkeypatch.setattr(ui.st, "warning", lambda value: messages.append(("warning", value)))
    monkeypatch.setattr(ui.st, "error", lambda value: messages.append(("error", value)))
    monkeypatch.setattr(ui.st, "success", lambda value: messages.append(("success", value)))
    monkeypatch.setattr(ui.st, "caption", lambda value: messages.append(("caption", value)))
    rows = []
    monkeypatch.setattr(ui.st, "dataframe", lambda value, **kw: rows.extend(value))
    monkeypatch.setattr(ui.st, "rerun", lambda: reruns.append(True))
    def sync(process, data):
        calls.append(("sync", process, data))
        if not state["facts"]:
            state["facts"] = [{"id": "f1", "status": "extraido",
                "path": "objeto.descricao", "valor": "Aquisição sintética",
                "fonte_campo": "objeto", "confianca": 1.0, "inferido": False}]
        return list(state["facts"])
    monkeypatch.setattr(ui.fatos, "sincronizar", sync)
    monkeypatch.setattr(ui.fatos, "confirmar_todos", lambda *a: 1)

    assert ui._preflight_fatos_aprovacao(processo) is False
    assert calls == [("sync", processo, {"objeto": "Aquisição sintética"})]
    assert rows == [{"Caminho": "objeto.descricao", "Valor": "Aquisição sintética",
                     "Campo de origem": "objeto", "Confiança": 1.0, "Inferido": False}]
    assert reruns == []

    buttons[confirm_key] = True
    def confirm(process, user):
        calls.append(("confirm", process, user))
        state["facts"] = [{"id": "f1", "status": "confirmado"}]
        return 1
    monkeypatch.setattr(ui.fatos, "confirmar_todos", confirm)
    assert ui._preflight_fatos_aprovacao(processo) is False
    assert calls[-1] == ("confirm", processo, session["usuario"]["id"])
    assert reruns == [True]

    buttons[confirm_key] = False
    assert ui._preflight_fatos_aprovacao(processo) is True
    assert ("caption", "Fatos canônicos confirmados: 1.") in messages


def test_preflight_fatos_nao_libera_estado_incompativel(monkeypatch):
    monkeypatch.setattr(ui.st, "session_state", Session())
    errors = []
    monkeypatch.setattr(ui.st, "error", errors.append)
    monkeypatch.setattr(ui.fatos, "sincronizar", lambda process, data:
        [{"id": "f1", "status": "revisao_humana"}])
    assert ui._preflight_fatos_aprovacao("11111111-1111-1111-1111-111111111111") is False
    assert errors and "estado incompatível" in errors[0]


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
        sequence = 3
        def receber_lote(self, batch, **kwargs):
            self.sequence = 4
            return checkpoint
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
    reruns = []
    monkeypatch.setattr(ui.st, "rerun", lambda: reruns.append(True))
    monkeypatch.setattr(ui, "replace", lambda current, **values: SimpleNamespace(**{**vars(current), **values}))
    ui._receber("tr", Service())
    assert confirmed == [{"request_id": operation, "revision": 4, "content_hash": "b" * 64}]
    assert session[ui._chave("tr", "preparation")] is None
    assert session[ui._chave("tr", "patch_receipt")] is batch_receipt
    assert session[ui._chave("tr", "document")].payload == b"patched"
    assert session[ui._chave("tr", "history")][-1]["canvas_confirmado"] is True
    assert reruns == [True]


def test_evento_de_controle_aceito_forca_rerun_para_publicar_event_ack(monkeypatch):
    class Bridge:
        instance_id = "33333333-3333-3333-3333-333333333333"
        document_id = "44444444-4444-4444-4444-444444444444"
        origin = "http://127.0.0.1:8501"
        sequence = 2
        def receber_lote(self, batch, **kwargs):
            assert batch == {"events": ["frozen"]}
            self.sequence = 3
            return None
        def canvas_bloqueado(self): return {"command_id": "freeze"}
        def falha_controle(self): return None
    class Service: pass
    bridge = Bridge()
    session = Session()
    session[ui._chave("tr", "bridge")] = bridge
    session["wordcraft_" + bridge.instance_id] = {"edit": {"events": ["frozen"]}}
    reruns = []
    monkeypatch.setattr(ui.st, "session_state", session)
    monkeypatch.setattr(ui.st, "rerun", lambda: reruns.append(True))

    ui._receber("tr", Service())

    assert bridge.sequence == 3
    assert session[ui._chave("tr", "message")] == "Canvas exato bloqueado para revisão."
    assert reruns == [True]

    # The component may resend the now-consumed prefix until it receives the
    # updated data payload.  A prefix that does not advance the bridge must not
    # schedule another rerun and recreate the production loop.
    ui._receber("tr", Service())
    assert bridge.sequence == 3
    assert reruns == [True]


def test_recusa_da_ponte_expoe_motivo_fechado_sem_consumir_lote(monkeypatch):
    from src.wordcraft_protocol import ErroPonte

    class Bridge:
        instance_id = "33333333-3333-3333-3333-333333333333"
        document_id = "44444444-4444-4444-4444-444444444444"
        origin = "http://127.0.0.1:8501"
        sequence = 7
        def receber_lote(self, batch, **kwargs):
            assert batch == {"events": ["late"]}
            raise ErroPonte("Documento indisponível para edição.")

    bridge = Bridge()
    session = Session({ui._chave("dfd", "bridge"): bridge,
        "wordcraft_" + bridge.instance_id: {"edit": {"events": ["late"]}}})
    monkeypatch.setattr(ui.st, "session_state", session)

    ui._receber("dfd", SimpleNamespace())

    assert bridge.sequence == 7
    assert session[ui._chave("dfd", "message")] == (
        "Operação nativa recusada: Documento indisponível para edição.")


def test_canvas_congelado_nao_e_remontado_durante_decisao_de_aprovacao():
    source = (Path(__file__).parents[1] /
        "src/ui/wordcraft_operacional.py").read_text(encoding="utf-8")
    tail = source[source.index("    with editor_slot:") :]
    assert "if proof is None:" in tail
    assert "render_editor(bridge" in tail
    assert "Editor pausado na revisão bloqueada" in tail
    assert "_reabrir_revisao_persistida(doc_key, service, runtime)" in source


def test_restore_operacional_usa_historico_persistido_cas_e_remonta_canvas(monkeypatch):
    document = SimpleNamespace(id="44444444-4444-4444-4444-444444444444",
        processo_id="11111111-1111-1111-1111-111111111111", tipo="tr",
        revision=3, content_hash="a" * 64, payload=b"current")
    restored = SimpleNamespace(**{**vars(document), "revision": 4,
        "content_hash": "b" * 64, "payload": b"restored"})
    receipt = SimpleNamespace(revision=4, content_hash="b" * 64)
    calls = []
    class Service:
        def restaurar(self, document_id, **kwargs):
            calls.append((document_id, kwargs))
            return receipt
        def abrir(self, document_id):
            assert document_id == document.id
            return restored
    session = Session()
    session[ui._chave("tr", "document")] = document
    session[ui._chave("tr", "bridge")] = SimpleNamespace(state="saved")
    session[ui._chave("tr", "history")] = [{"kind": "revision", "revision": 1}]
    session[ui._chave("tr", "audit")] = {"stale": True}
    monkeypatch.setattr(ui.st, "session_state", session)
    monkeypatch.setattr(ui, "_montar", lambda key, value, runtime:
        session.__setitem__(ui._chave(key, "document"), value))
    ui._restaurar_operacional("tr", Service(), object(), 1)
    assert calls == [(document.id, {"source_revision": 1, "expected_revision": 3,
        "operation_id": str(uuid5(NAMESPACE_URL,
            "govconnect-wordcraft-restore:" + document.id + ":3:1"))})]
    assert session[ui._chave("tr", "document")] is restored
    assert ui._chave("tr", "history") not in session
    assert ui._chave("tr", "audit") not in session
    assert "nova revisão 4" in session[ui._chave("tr", "message")]


def test_confirmacoes_em_form_nao_criam_botoes_impossiveis_de_habilitar():
    source = (Path(__file__).parents[1] / "src/ui/wordcraft_operacional.py").read_text(
        encoding="utf-8")
    template = source[source.index('with st.form(_chave(doc_key, "template_apply_form"))'):
                      source.index('if st.button("Carregar histórico persistido"')]
    restore_start = source.index('with st.form(_chave(doc_key, "restore_form"))')
    restore = source[restore_start:
                     source.index('current_audit = st.session_state.get(audit_key)', restore_start)]

    assert "disabled=not can_apply or not template_confirmed" not in template
    assert "if not template_confirmed:" in template
    assert "disabled=not restore_confirmed" not in restore
    assert "if not restore_confirmed:" in restore


def test_controles_de_aprovacao_sao_renderizados_antes_da_espera_do_canvas():
    source = (Path(__file__).parents[1] / "src/ui/wordcraft_operacional.py").read_text(
        encoding="utf-8")
    render = source[source.index("def render(doc_key") : source.index("def render_sucesso")]

    reserved = render.index("editor_slot = st.empty()")
    freeze = render.index('st.button("Revisar e preparar aprovação"')
    approve = render.index('aprovar.button(f"Aprovar {meta[\'sigla\']}"')
    mounted = render.index("with editor_slot:")
    component = render.index("render_editor(", mounted)

    assert reserved < freeze < approve < mounted < component
    assert "facts_ready = _preflight_fatos_aprovacao(processo_id)" in render
    assert "disabled=not facts_ready or bridge.state" in render
    assert "disabled=not facts_ready," in render


def test_template_operacional_prepara_confirma_reabre_e_remonta_head(monkeypatch):
    process = "11111111-1111-1111-1111-111111111111"
    version = "55555555-5555-5555-5555-555555555555"
    document = SimpleNamespace(id="44444444-4444-4444-4444-444444444444",
        processo_id=process, tipo="tr", revision=3, content_hash="a" * 64,
        payload=b"current", index_mode="reconciled")
    applied = SimpleNamespace(**{**vars(document), "revision": 4,
        "content_hash": "b" * 64, "payload": b"templated",
        "index_mode": "template_application"})
    prepared = object()
    receipt = SimpleNamespace(revision=4, content_hash="b" * 64)
    calls = []
    class Service:
        def preparar_template(self, process_id, doc_key, version_id, operation_id):
            calls.append(("prepare", process_id, doc_key, version_id, operation_id))
            return prepared
        def confirmar_template(self, value):
            assert value is prepared
            calls.append(("confirm", value))
            return receipt
        def abrir(self, document_id):
            assert document_id == document.id
            return applied
    session = Session()
    session[ui._chave("tr", "document")] = document
    session[ui._chave("tr", "bridge")] = SimpleNamespace(state="ready")
    invalidated = ("preparation", "audit", "legal_opinions", "legal_attendance",
        "evidence", "citation_check", "structure", "template_preview", "history",
        "patch_receipt", "approval")
    for suffix in invalidated:
        session[ui._chave("tr", suffix)] = {"stale": True}
    monkeypatch.setattr(ui.st, "session_state", session)
    monkeypatch.setattr(ui, "_montar", lambda key, value, runtime:
        session.__setitem__(ui._chave(key, "document"), value))
    ui._aplicar_template_operacional("tr", Service(), object(), process, version)
    expected_operation = str(uuid5(NAMESPACE_URL, "govconnect-wordcraft-template:"
        + document.id + ":3:" + version))
    assert calls == [("prepare", process, "tr", version, expected_operation),
                     ("confirm", prepared)]
    assert session[ui._chave("tr", "document")] is applied
    assert all(ui._chave("tr", suffix) not in session for suffix in invalidated)
    assert "revisão nativa 4" in session[ui._chave("tr", "message")]


def test_restore_options_ignore_receipts_current_and_divergent_rows():
    history = [
        {"kind": "revision", "revision": 3, "current": True},
        {"kind": "receipt", "revision": 2, "current": False},
        {"kind": "revision", "revision": 2, "current": False},
        {"kind": "revision", "revision": 1, "current": False},
        {"kind": "revision", "revision": True, "current": False},
        {"kind": "revision", "revision": 4, "current": False},
    ]
    assert ui._revisoes_restauraveis(history, 3) == (2, 1)


def test_reabre_transporte_recusado_so_da_mesma_revisao_persistida(monkeypatch):
    from src.wordcraft_protocol import Ponte
    from tests.test_wordcraft_protocol import evento, receber

    document = SimpleNamespace(id="44444444-4444-4444-4444-444444444444",
        processo_id="11111111-1111-1111-1111-111111111111", tipo="dfd",
        revision=8, content_hash="a" * 64, status="rascunho", payload=b"persisted")
    bridge = Ponte("http://localhost:8884", "22222222-2222-2222-2222-222222222222",
        "33333333-3333-3333-3333-333333333333", document.id, "n" * 48,
        revision=document.revision, content_hash=document.content_hash)
    receber(bridge, evento(bridge, "loaded", {"content_hash": document.content_hash}))
    operation = "55555555-5555-5555-5555-555555555555"
    bridge.solicitar_bloqueio(operation)
    receber(bridge, evento(bridge, "frozen", dict(command_id=operation,
        content_hash=document.content_hash, generation="1")))
    component_key = "wordcraft_" + bridge.instance_id
    session = Session({ui._chave("dfd", "document"): document,
        ui._chave("dfd", "bridge"): bridge, component_key: {"edit": "poisoned"}})
    monkeypatch.setattr(ui.st, "session_state", session)
    mounted = []
    monkeypatch.setattr(ui, "_montar", lambda key, value, runtime:
        mounted.append((key, value, runtime)))
    service = SimpleNamespace(abrir=lambda document_id: document)
    runtime = object()

    ui._reabrir_revisao_persistida("dfd", service, runtime)

    assert mounted == [("dfd", document, runtime)]
    assert component_key not in session
    assert "mesma revisão persistida" in session[ui._chave("dfd", "message")]


def test_reabertura_recusa_checkpoint_pendente_ou_head_divergente(monkeypatch):
    from src.wordcraft_protocol import Ponte
    from tests.test_wordcraft_protocol import evento, receber

    document = SimpleNamespace(id="44444444-4444-4444-4444-444444444444",
        processo_id="11111111-1111-1111-1111-111111111111", tipo="dfd",
        revision=8, content_hash="a" * 64, status="rascunho", payload=b"persisted")
    bridge = Ponte("http://localhost:8884", "22222222-2222-2222-2222-222222222222",
        "33333333-3333-3333-3333-333333333333", document.id, "n" * 48,
        revision=document.revision, content_hash=document.content_hash)
    receber(bridge, evento(bridge, "loaded", {"content_hash": document.content_hash}))
    operation = "55555555-5555-5555-5555-555555555555"
    bridge.solicitar_bloqueio(operation)
    receber(bridge, evento(bridge, "frozen", dict(command_id=operation,
        content_hash=document.content_hash, generation="1")))
    session = Session({ui._chave("dfd", "document"): document,
        ui._chave("dfd", "bridge"): bridge})
    monkeypatch.setattr(ui.st, "session_state", session)
    bridge._pending = object()
    with pytest.raises(ui.ErroDocumento, match="revisão limpa"):
        ui._reabrir_revisao_persistida("dfd", SimpleNamespace(), object())

    bridge._pending = None
    changed = SimpleNamespace(**{**vars(document), "revision": 9,
        "content_hash": "b" * 64})
    with pytest.raises(ui.ConflitoDocumento, match="head mudou"):
        ui._reabrir_revisao_persistida("dfd",
            SimpleNamespace(abrir=lambda document_id: changed), object())


def test_reabre_falha_transitoria_so_da_mesma_revisao_persistida(monkeypatch):
    from src.wordcraft_protocol import Ponte
    from tests.test_wordcraft_protocol import evento, receber

    document = SimpleNamespace(id="44444444-4444-4444-4444-444444444444",
        processo_id="11111111-1111-1111-1111-111111111111", tipo="dfd",
        revision=8, content_hash="a" * 64, status="rascunho", payload=b"persisted")
    bridge = Ponte("http://localhost:8884", "22222222-2222-2222-2222-222222222222",
        "33333333-3333-3333-3333-333333333333", document.id, "n" * 48,
        revision=document.revision, content_hash=document.content_hash)
    receber(bridge, evento(bridge, "loaded", {"content_hash": document.content_hash}))
    operation = "55555555-5555-5555-5555-555555555555"
    bridge.solicitar_bloqueio(operation)
    receber(bridge, evento(bridge, "control_failed", dict(
        command_id=operation, reason="unavailable")))
    component_key = "wordcraft_" + bridge.instance_id
    session = Session({ui._chave("dfd", "document"): document,
        ui._chave("dfd", "bridge"): bridge, component_key: {"edit": "poisoned"}})
    monkeypatch.setattr(ui.st, "session_state", session)
    mounted = []
    monkeypatch.setattr(ui, "_montar", lambda key, value, runtime:
        mounted.append((key, value, runtime)))
    runtime = object()

    ui._reabrir_falha_controle_persistida("dfd",
        SimpleNamespace(abrir=lambda document_id: document), runtime)

    assert mounted == [("dfd", document, runtime)]
    assert component_key not in session
    assert "mesma revisão persistida" in session[ui._chave("dfd", "message")]


def test_reabertura_de_controle_recusa_dirty_e_head_divergente(monkeypatch):
    from src.wordcraft_protocol import Ponte
    from tests.test_wordcraft_protocol import evento, receber

    document = SimpleNamespace(id="44444444-4444-4444-4444-444444444444",
        processo_id="11111111-1111-1111-1111-111111111111", tipo="dfd",
        revision=8, content_hash="a" * 64, status="rascunho", payload=b"persisted")
    bridge = Ponte("http://localhost:8884", "22222222-2222-2222-2222-222222222222",
        "33333333-3333-3333-3333-333333333333", document.id, "n" * 48,
        revision=document.revision, content_hash=document.content_hash)
    receber(bridge, evento(bridge, "loaded", {"content_hash": document.content_hash}))
    operation = "55555555-5555-5555-5555-555555555555"
    bridge.solicitar_bloqueio(operation)
    receber(bridge, evento(bridge, "control_failed", dict(
        command_id=operation, reason="dirty")))
    session = Session({ui._chave("dfd", "document"): document,
        ui._chave("dfd", "bridge"): bridge})
    monkeypatch.setattr(ui.st, "session_state", session)
    with pytest.raises(ui.ErroDocumento, match="edição suja"):
        ui._reabrir_falha_controle_persistida("dfd", SimpleNamespace(), object())

    bridge._control_failure = {"command_id": operation, "reason": "stale"}
    changed = SimpleNamespace(**{**vars(document), "revision": 9,
        "content_hash": "b" * 64})
    with pytest.raises(ui.ConflitoDocumento, match="head mudou"):
        ui._reabrir_falha_controle_persistida("dfd",
            SimpleNamespace(abrir=lambda document_id: changed), object())


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
