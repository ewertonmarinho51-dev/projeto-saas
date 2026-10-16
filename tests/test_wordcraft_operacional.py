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


def test_steps_troca_a_superficie_inteira_antes_do_editor_legado():
    source = (Path(__file__).parents[1] / "src/ui/steps.py").read_text(encoding="utf-8")
    start = source.index("if wordcraft_runtime.ativo():")
    rich = source.index('if db.flag_ativa("editor_rico"):', start)
    segment = source[start:rich]
    assert "render_wordcraft(doc_key, meta)" in segment
    assert "return" in segment
