"""
G2 (pacote de 17/10/2026) — concluir o item e ir para o próximo.

Cenários do pacote (04_FLUXO_CONCLUIR_PROXIMO_ITEM): A) 1→2; B) 2→3;
C) 3 com o 1 pendente → 1; D) único/último → resumo; E) erro → fica;
F) reordenados → ordem corrente; G) retirados ignorados; H) concluído
ignorado; I) conflito → fica; J) aplicada/arquivada → sem botão.

A regra é a função pura `cotacoes.proximo_item_para_revisao`; a tela só
a usa DEPOIS de `concluir_item` confirmar.
"""

from __future__ import annotations

import pytest

from src.precos import cotacoes
from src.precos import repositorio as repo
from tests.test_cotacoes_g2_servico import CTX, ITEM, _fonte
from tests.test_cotacoes_g2_ui import _app, _botao


def _i(numero, estado="review", **extra):
    return {"id": f"i{numero}", "numero": numero, "estado": estado, **extra}


# ---------------------------------------------------------------------------
# Função pura
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("itens, atual, esperado", [
    ([_i(1), _i(2), _i(3)], "i1", "i2"),                         # A
    ([_i(1), _i(2), _i(3)], "i2", "i3"),                         # B
    ([_i(1), _i(2, "complete"), _i(3)], "i3", "i1"),             # C
    ([_i(1)], "i1", None),                                       # D
    ([_i(1), _i(2, "complete"), _i(3, "complete")], "i1", None),  # D
    ([_i(3), _i(1), _i(2)], "i1", "i2"),                         # F (ordem)
    ([_i(1), _i(2, removido_em="2026-10-17"), _i(3)], "i1", "i3"),  # G
    ([_i(1), _i(2, "complete"), _i(3)], "i1", "i3"),             # H
    ([_i(1), _i(2, "incomplete"), _i(3)], "i1", "i2"),           # difícil não pula
    ([_i(1), _i(2, "error")], "i1", "i2"),
])
def test_proximo_item(itens, atual, esperado):
    proximo = cotacoes.proximo_item_para_revisao(itens, atual)
    assert (proximo or {}).get("id") == esperado


def test_numero_mudado_pela_reordenacao_vale():
    """F: o servidor desceu o item 2 para o fim — vale a ordem nova."""
    itens = [_i(1), _i(3, id="iB"), _i(2, id="iC")]
    assert cotacoes.proximo_item_para_revisao(itens, "i1")["id"] == "iC"


# ---------------------------------------------------------------------------
# Tela (AppTest, app inteiro, banco falso)
# ---------------------------------------------------------------------------
def _cotacao_em_revisao(monkeypatch, n=3):
    from src.ui import cotacoes_ui

    at, cliente = _app(monkeypatch, unificada=True, pagina="Cotações")
    c = cotacoes.criar_cotacao(CTX, {"nome": "Avanço"})
    ids = []
    for k in range(n):
        item = cotacoes.salvar_item(
            CTX, str(c["id"]), {**ITEM, "descricao": f"PAPEL A4 75G {k}"})
        cotacoes.pesquisar_item(CTX, str(c["id"]), str(item["id"]),
                                modo="automatico", fontes=[_fonte()])
        ids.append(str(item["id"]))
    at.session_state[cotacoes_ui.TELA] = cotacoes_ui.ELABORAR
    at.session_state[cotacoes_ui.COTACAO] = str(c["id"])
    at.session_state[cotacoes_ui.ITEM] = ids[0]
    return at, str(c["id"]), ids


def _concluir(at, justificativa="conferido na fonte oficial"):
    area = next(t for t in at.text_area
                if t.label.startswith(("Justificativa", "Observação")))
    area.input(justificativa)
    _botao(at, "Concluir item").click().run()


def test_concluir_abre_o_proximo_e_mantem_o_filtro(monkeypatch):
    from src.ui import cotacoes_ui

    at, cid, ids = _cotacao_em_revisao(monkeypatch)
    at.session_state["cot_filtro_itens"] = "papel"
    at.run()
    _concluir(at)
    assert not at.exception
    assert repo.obter_item(ids[0])["estado"] == "complete"
    assert at.session_state[cotacoes_ui.ITEM] == ids[1]
    assert at.session_state["cot_filtro_itens"] == "papel"
    assert any("Abrindo o item 02" in str(t.value) for t in at.toast)
    textos = " ".join(str(m.value) for m in at.markdown)
    assert "Item 02" in textos


def test_ultimo_item_abre_a_conclusao_da_cotacao(monkeypatch):
    from src.ui import cotacoes_ui

    at, cid, ids = _cotacao_em_revisao(monkeypatch, n=1)
    at.run()
    _concluir(at)
    assert not at.exception
    assert at.session_state[cotacoes_ui.ITEM] == ids[0]
    assert at.session_state["cot_painel_relatorio"] is True
    assert any(b.label == "Concluir cotação" for b in at.button)


def test_recusa_da_validacao_nao_avanca(monkeypatch):
    from src.ui import cotacoes_ui

    at, cid, ids = _cotacao_em_revisao(monkeypatch)
    at.run()
    monkeypatch.setattr(cotacoes, "concluir_item", lambda *a, **k: (
        _ for _ in ()).throw(cotacoes.ErroCotacao("justificativa curta")))
    _concluir(at, "x")
    assert not at.exception
    assert at.session_state[cotacoes_ui.ITEM] == ids[0]
    assert any("justificativa curta" in str(e.value) for e in at.error)


def test_conflito_de_versao_nao_avanca(monkeypatch):
    from src.ui import cotacoes_ui

    at, cid, ids = _cotacao_em_revisao(monkeypatch)
    at.run()
    # outra aba mexe no item depois que esta o mostrou
    repo.atualizar_item(ids[0], {"quantidade": "11"},
                        revisao_esperada=int(repo.obter_item(ids[0])["revisao"]))
    _concluir(at)
    assert not at.exception
    assert repo.obter_item(ids[0])["estado"] == "review"
    assert at.session_state[cotacoes_ui.ITEM] == ids[0]
    assert any("outra aba" in str(w.value) for w in at.warning)


def test_erro_de_banco_nao_avanca(monkeypatch):
    from src import db
    from src.ui import cotacoes_ui

    at, cid, ids = _cotacao_em_revisao(monkeypatch)
    at.run()
    monkeypatch.setattr(cotacoes, "concluir_item", lambda *a, **k: (
        _ for _ in ()).throw(db.ErroBanco("banco indisponível")))
    _concluir(at)
    assert not at.exception
    assert at.session_state[cotacoes_ui.ITEM] == ids[0]


def test_concorrencia_outra_aba_concluiu_o_proximo(monkeypatch):
    """O estado é relido: o item que outra aba concluiu é pulado."""
    from src.ui import cotacoes_ui

    at, cid, ids = _cotacao_em_revisao(monkeypatch)
    at.run()
    cotacoes.concluir_item(CTX, cid, ids[1], justificativa="outra aba")
    _concluir(at)
    assert at.session_state[cotacoes_ui.ITEM] == ids[2]


def test_cotacao_arquivada_nao_oferece_concluir(monkeypatch):
    at, cid, ids = _cotacao_em_revisao(monkeypatch)
    cotacoes.arquivar(CTX, cid)
    at.run()
    assert not at.exception
    assert not any(b.label == "Concluir item" for b in at.button)
