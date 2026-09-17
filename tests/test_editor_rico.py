import pytest

from src.ui.rich_editor import aceitar_evento, hash_texto, html_do_markdown


def sessao(texto="Original"):
    return {"documentos": {"etp": texto}, "_rich_editors": {
        "etp": {"version": "v1", "sequence": 0}}, "aprovados": {"etp"}}


def evento(texto="Alterado", **extra):
    return {"version": "v1", "source": hash_texto("Original"),
            "sequence": 1, "markdown": texto, "action": "draft", **extra}


def test_rascunho_nao_aprova_nem_substitui_canonico():
    s = sessao()
    assert aceitar_evento(s, "etp", evento()) == ("draft", "Alterado")
    assert s["documentos"] == {"etp": "Original"}
    assert s["edicoes_pendentes"] == {"etp": "Alterado"}
    assert s["aprovados"] == {"etp"}


@pytest.mark.parametrize("extra", [{"version": "antiga"}, {"source": "outra"},
                                  {"sequence": 0}, {"sequence": True},
                                  {"action": "apply"}])
def test_evento_obsoleto_ou_forjado_nao_escreve(extra):
    s = sessao()
    assert aceitar_evento(s, "etp", evento(**extra)) is None
    assert "edicoes_pendentes" not in s


def test_replay_e_mudanca_de_documento_pelo_govbot():
    s = sessao()
    aceitar_evento(s, "etp", evento())
    assert aceitar_evento(s, "etp", evento("Replay")) is None
    s["documentos"]["etp"] = "Patch aprovado"
    assert aceitar_evento(s, "etp", evento("Antigo", sequence=2)) is None
    assert s["documentos"]["etp"] == "Patch aprovado"


def test_aprovacao_sem_edicao_preserva_markdown_literal():
    original = "A & B <https://example.org> **ação**\n\n| A | B |\n|---|---|\n| x<br>y | 2 |"
    s = sessao(original)
    aceito = aceitar_evento(s, "etp", evento(original, source=hash_texto(original), action="approve"))
    assert aceito == ("approve", original)
    assert s["edicoes_pendentes"] == {}


def test_renderizacao_nao_executa_html_ou_urls_ativas():
    html = html_do_markdown('<script>alert(1)</script> [x](javascript:alert(1))\n\n**ação** & B')
    assert "<script>" not in html
    assert 'href="javascript:' not in html
    assert "<strong>ação</strong>" in html


def test_correcao_externa_substitui_rascunho_da_versao_antiga(monkeypatch):
    from src.ui import rich_editor
    s = sessao()
    s["_rich_editors"]["etp"]["source"] = hash_texto(s["documentos"]["etp"])
    s["editor_etp"] = "Rascunho antigo"
    s["edicoes_pendentes"] = {"etp": "Rascunho antigo"}
    s["documentos"]["etp"] = "Corrigido por parecer"
    recebido = {}
    def componente(**kwargs):
        recebido.update(kwargs["data"])
    monkeypatch.setattr(rich_editor.st, "session_state", s)
    monkeypatch.setattr(rich_editor, "_renderer", lambda: componente)
    acao, texto = rich_editor.render_editor("etp", s["documentos"]["etp"])
    assert texto == recebido["markdown"] == "Corrigido por parecer"
    assert not s["edicoes_pendentes"]
    assert acao is None
