"""
G6 — ponta a ponta no serviço de Cotações (matriz do `07_GATES` G6).

Mesma fixture sintética do benchmark (descrições e unidades do caso real
de 210 itens; fontes dublês determinísticas). Banco falso das provas de
preços: isolamento por RLS NÃO é provado aqui — é provado contra
PostgreSQL em `test_precos_fase3_rls.py` / `test_migracao_0029.py`
quando o banco de ensaio existe. O que se prova aqui é o contrato do
serviço: nada se perde, nada se duplica, nenhum preço é fabricado.
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from scripts import benchmark_cotacoes as bench
from src.precos import cesta, cotacoes, relatorio
from src.precos import repositorio as repo
from tests.cotacoes_apoio import ligar_banco_falso
from tests.test_cotacoes_g2_servico import CTX, ITEM, _fonte


def _cotacao_com(n, monkeypatch):
    cliente = ligar_banco_falso(monkeypatch)
    fonte = bench.FonteSintetica()
    itens = bench._itens(n)
    for item in itens:
        fonte.registrar(item)
    cotacao = cotacoes.criar_cotacao(CTX, {"nome": f"E2E {n}",
                                           "data_base": "2026-10-16"})
    for item in itens:
        cotacoes.salvar_item(CTX, str(cotacao["id"]), {
            "descricao": item["descricao"], "unidade": item["unidade"],
            "quantidade": item["quantidade"], "codigo": item["codigo"]})
    return cliente, str(cotacao["id"]), fonte, itens


def _rodar_lote(cid, fonte, tamanho=10):
    tentados: set[str] = set()
    while True:
        _, restantes = cotacoes.pesquisar_em_lote(
            CTX, cid, modo="automatico", tamanho=tamanho,
            ja_tentados=tentados, fontes=[fonte])
        if not restantes:
            return tentados


@pytest.mark.parametrize("n", [1, 10, 50, 210])
def test_lote_automatico_preserva_itens_e_nao_fabrica_preco(n, monkeypatch):
    cliente, cid, fonte, itens = _cotacao_com(n, monkeypatch)
    _rodar_lote(cid, fonte)
    finais = cotacoes.ativos(repo.listar_itens(cid))
    assert len(finais) == n and len(cliente.tabelas["pesquisa_preco_itens"]) == n
    assert [i["codigo"] for i in finais] == [i["codigo"] for i in itens]
    assert all(i["estado"] != "pending" for i in finais)
    for numero, linha in enumerate(finais, start=1):
        cenario = bench._cenario(numero)
        if cenario in ("zero", "vizinhos", "fonte_fora"):
            assert linha.get("preco_estimado") is None, (numero, cenario)
        if cenario == "fonte_fora":
            assert linha["estado"] == "error"
        if cenario == "dois":
            assert (cesta.na_cesta_do_item(linha) or 0) == 2
            assert linha["estado"] == "incomplete"
    # reexecutar não duplica referência nenhuma
    antes = len(cliente.tabelas["pesquisa_preco_referencias"])
    _rodar_lote(cid, fonte)
    assert len(cliente.tabelas["pesquisa_preco_referencias"]) == antes
    # uma chamada de fonte por item processado, nenhuma de IA
    assert fonte.chamadas <= n + sum(1 for k in range(1, n + 1)
                                     if bench._cenario(k) == "fonte_fora")


def test_50_itens_cancelar_no_meio_e_retomar(monkeypatch):
    _, cid, fonte, _ = _cotacao_com(50, monkeypatch)
    tentados: set[str] = set()
    for _ in range(3):   # três passos e "fecha a aba"
        cotacoes.pesquisar_em_lote(CTX, cid, modo="automatico", tamanho=5,
                                   ja_tentados=tentados, fontes=[fonte])
    feitos = [i for i in repo.listar_itens(cid) if i["estado"] != "pending"]
    assert len(feitos) == 15
    # outra sessão retoma sem o conjunto da primeira: pega só os pendentes
    chamadas_antes = fonte.chamadas
    _rodar_lote(cid, fonte)
    assert fonte.chamadas - chamadas_antes == 35
    assert all(i["estado"] != "pending" for i in repo.listar_itens(cid))


def test_10_itens_manual_e_automatico_na_mesma_cotacao(monkeypatch):
    cliente, cid, fonte, _ = _cotacao_com(10, monkeypatch)
    [primeiro, *resto] = cotacoes.ativos(repo.listar_itens(cid))
    cotacoes.pesquisar_item(CTX, cid, str(primeiro["id"]), modo="manual",
                            fontes=[fonte])
    _rodar_lote(cid, fonte)
    assert len(cliente.tabelas["pesquisas_preco"]) == 1
    estados = {i["estado"] for i in repo.listar_itens(cid)}
    assert "pending" not in estados
    # o item manual não teve a cesta montada pela máquina ANTES do lote,
    # e o lote não o refez (já tinha sido pesquisado)
    assert repo.obter_item(str(primeiro["id"]))["estado"] == "incomplete"


def test_1_item_tres_precos_com_um_excluido_fica_dois_de_tres(monkeypatch):
    ligar_banco_falso(monkeypatch)
    c = cotacoes.criar_cotacao(CTX, {"nome": "2/3"})
    item = cotacoes.salvar_item(CTX, str(c["id"]), ITEM)
    cotacoes.pesquisar_item(CTX, str(c["id"]), str(item["id"]),
                            modo="automatico",
                            fontes=[_fonte(("29.00", "22.70", "9.66"))])
    assert Decimal(str(repo.obter_item(str(item["id"]))["preco_estimado"])) \
        == Decimal("20.45")
    alvo = next(r for r in repo.listar_referencias(str(item["id"]))
                if Decimal(str(r["valor_unitario_normalizado"])) == Decimal("9.66"))
    cotacoes.alterar_status_referencia(CTX, str(c["id"]), str(item["id"]),
                                       str(alvo["id"]), incluir=False,
                                       motivo="inexequível frente aos demais")
    linha = repo.obter_item(str(item["id"]))
    assert Decimal(str(linha["preco_estimado"])) == Decimal("25.85")
    assert linha["estado"] == "incomplete"
    assert cesta.na_cesta_do_item(linha) == 2
    texto = relatorio.completo(repo.obter_pesquisa(str(c["id"])), [linha],
                               {str(item["id"]): repo.listar_referencias(
                                   str(item["id"]))})
    assert "2/3 preços considerados" in texto


def test_cotacao_fora_do_alcance_e_recusada_mesmo_com_id_conhecido(monkeypatch):
    """O RLS devolve vazio para o tenant B; o serviço não 'acha' a cotação."""
    _, cid, fonte, _ = _cotacao_com(1, monkeypatch)
    item_id = str(repo.listar_itens(cid)[0]["id"])
    monkeypatch.setattr(repo, "obter_pesquisa", lambda _id: None)
    for chamada in (
            lambda: cotacoes.pesquisar_item(CTX, cid, item_id, fontes=[fonte]),
            lambda: cotacoes.salvar_item(CTX, cid, ITEM),
            lambda: cotacoes.concluir_item(CTX, cid, item_id),
            lambda: cotacoes.alterar_status_referencia(
                CTX, cid, item_id, "x", incluir=True, motivo="m")):
        with pytest.raises(cotacoes.ErroCotacao, match="fora do seu acesso"):
            chamada()


def test_sem_sessao_o_servico_nao_cai_para_a_credencial_de_servidor(monkeypatch):
    from src import db

    monkeypatch.setattr(db, "cliente_do_usuario", lambda: None)
    with pytest.raises(repo.SemSessao):
        cotacoes.listar_cotacoes(CTX)
