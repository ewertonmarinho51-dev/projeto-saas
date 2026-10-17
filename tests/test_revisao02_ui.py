"""
Revisão 02 — a tela de Cotações no AppTest (app inteiro, banco falso).

AC-09 remover sem justificativa + Desfazer; AC-24 alerta com valor, órgão
e data e as ações ao lado; AC-26 nada de "Item.", "completa", "Com 3+
considerado" ou "Para mudar, reabra…"; item concluído sem "revise antes de
concluir".
"""

from __future__ import annotations

from src.precos import cesta, cotacoes
from src.precos import repositorio as repo
from tests.test_cotacoes_g2_ui import _app, _botao
from tests.test_revisao02_triagem import CTX, FonteDaMassa

VALORES = ("10", "10.5", "11", "10.2", "10.8", "40")


def _massa(valores=VALORES) -> dict:
    return {"id": "R", "number": 1, "description": "PRODUTO TESTE",
            "unit": "UNIDADE", "package_size": 1, "quantity": 10,
            "references": [{"id": f"R{i}", "same_origin_key": f"P{i}",
                            "description": "PRODUTO TESTE", "unit": "UNIDADE",
                            "package_size": 1, "price_original": v,
                            "source": "F", "organization": "ORG",
                            "source_url": None}
                           for i, v in enumerate(valores)]}


def _tela_com_cesta(monkeypatch):
    from src.ui import cotacoes_ui

    at, cliente = _app(monkeypatch, unificada=True, pagina="Cotações")
    cotacao = cotacoes.criar_cotacao(CTX, {"nome": "Revisão 02"})
    item = cotacoes.salvar_item(CTX, str(cotacao["id"]), {
        "descricao": "PRODUTO TESTE", "unidade": "UNIDADE",
        "quantidade": "10"})
    cotacoes.pesquisar_item(CTX, str(cotacao["id"]), str(item["id"]),
                            modo="automatico", fontes=[FonteDaMassa(_massa())])
    at.session_state[cotacoes_ui.TELA] = cotacoes_ui.ELABORAR
    at.session_state[cotacoes_ui.COTACAO] = str(cotacao["id"])
    at.run()
    assert not at.exception
    return at, cliente, str(cotacao["id"]), str(item["id"])


def _texto(at) -> str:
    partes = [str(m.value) for m in at.markdown] + \
        [str(c.value) for c in at.caption] + \
        [str(m.label) for m in at.metric] + [str(b.label) for b in at.button]
    for tipo in (at.success, at.info, at.warning, at.error):
        partes += [str(x.value) for x in tipo]
    return " ".join(partes)


def test_remover_um_clique_sem_justificativa_e_desfazer_ac09(monkeypatch):
    at, _, _, iid = _tela_com_cesta(monkeypatch)
    antes = len(cesta.consideradas(repo.listar_referencias(iid)))
    _botao(at, "Remover da cesta").click().run()
    assert not at.exception
    assert len(cesta.consideradas(repo.listar_referencias(iid))) == antes - 1
    texto = _texto(at)
    assert "removido da cesta" in texto and "Estimativa atualizada." in texto
    _botao(at, "Desfazer").click().run()
    assert not at.exception
    assert len(cesta.consideradas(repo.listar_referencias(iid))) == antes


def test_alerta_mostra_preco_origem_e_acoes_e_manter_tira_pendencia_ac24(
        monkeypatch):
    at, _, _, iid = _tela_com_cesta(monkeypatch)
    texto = _texto(at)
    assert "Confira este preço" in texto
    assert "R\\$ 40,00" in texto or "R$ 40,00" in texto
    assert "ORG P5" in texto, "órgão de origem na linha do alerta"
    assert "Os demais preços usados estão entre" in texto
    assert "IQR" not in texto and "MAD" not in texto and "-R$" not in texto
    assert any("atípico" in p for p in
               repo.obter_item(iid)["estatisticas"]["pendencias"])
    _botao(at, "Manter preço").click().run()
    assert not at.exception
    assert not any("atípico" in p for p in
                   repo.obter_item(iid)["estatisticas"]["pendencias"])
    assert "Mantido no cálculo por sua decisão." in _texto(at)


def test_rotulos_sem_funcao_sumiram_ac26(monkeypatch):
    at, _, cid, iid = _tela_com_cesta(monkeypatch)
    texto = _texto(at)
    for proibido in ("Com 3+ considerado", "/3 considerado",
                     "Para mudar, reabra", "Item.", "valor provisório"):
        assert proibido not in texto, proibido
    assert "Com preços suficientes" in texto
    assert "preços usados (mínimo 3)" in texto


def test_item_concluido_nao_pede_revisao_antes_de_concluir(monkeypatch):
    at, _, cid, iid = _tela_com_cesta(monkeypatch)
    alvo = next(l for l in repo.listar_referencias(iid)
                if l["valor_unitario_original"] == "40")
    cotacoes.alterar_status_referencia(CTX, cid, iid, str(alvo["id"]),
                                       incluir=False)
    cotacoes.concluir_item(CTX, cid, iid, justificativa="")
    at.run()
    texto = _texto(at)
    assert "Pesquisa do item concluída." in texto
    assert "revise antes de concluir" not in texto.lower()
    assert "Preço formado com" not in texto, "item concluído: sem aviso"
