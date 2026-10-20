"""
G2 — serviço de Cotações: uma cotação, um item, manual e automático no
MESMO documento e na MESMA cesta (pacote: U01, U03, U04, U06, U07).

Banco falso das provas de preços e fontes dublês; nenhuma rede, nenhuma IA.
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from src.precos import cotacoes
from src.precos import repositorio as repo
from src.precos.estados import EstadoItem
from tests.cotacoes_apoio import FONTE_ITENS, ligar_banco_falso, referencia
from tests.test_precos_fase4 import _FonteFalsa

CTX = cotacoes.Contexto(auth_user_id="u1")
ITEM = {"descricao": "PAPEL SULFITE A4 75G", "unidade": "RESMA",
        "quantidade": "10"}


def _fonte(valores=("20.00", "22.00", "24.00", "26.00", "28.00"),
           descricao="PAPEL SULFITE A4 75G", explode=False):
    return _FonteFalsa(FONTE_ITENS.__class__(
        "compras_gov_precos", "Compras.gov — preços praticados",
        "sistema_oficial"),
        [referencia(v, f"r{i}", descricao=descricao)
         for i, v in enumerate(valores)], explode=explode)


def _nova(monkeypatch, **dados):
    cliente = ligar_banco_falso(monkeypatch)
    cotacao = cotacoes.criar_cotacao(
        CTX, {"nome": "Expediente 2026", **dados}, idempotency_key="k1")
    item = cotacoes.salvar_item(CTX, str(cotacao["id"]), ITEM)
    return cliente, str(cotacao["id"]), str(item["id"])


def test_u01_identidade_antes_dos_itens_e_reabertura(monkeypatch):
    cliente = ligar_banco_falso(monkeypatch)
    with pytest.raises(cotacoes.ErroCotacao, match="nome"):
        cotacoes.criar_cotacao(CTX, {"nome": "  "})
    with pytest.raises(cotacoes.ErroCotacao, match="255"):
        cotacoes.criar_cotacao(CTX, {"nome": "x" * 256})
    criada = cotacoes.criar_cotacao(CTX, {"nome": "Vazia"}, idempotency_key="a")
    de_novo = cotacoes.criar_cotacao(CTX, {"nome": "Vazia"}, idempotency_key="a")
    assert criada["id"] == de_novo["id"]
    assert len(cliente.tabelas["pesquisas_preco"]) == 1
    reaberta = repo.obter_pesquisa(str(criada["id"]))
    assert reaberta["estado"] == "draft" and repo.listar_itens(str(criada["id"])) == []


def test_item_invalido_e_recusado_com_motivo(monkeypatch):
    _, cid, _ = _nova(monkeypatch)
    for dados, motivo in (({**ITEM, "unidade": "Caixotes"}, "Caixotes"),
                          ({**ITEM, "quantidade": "abc"}, "quantidade"),
                          ({**ITEM, "quantidade": "0"}, "maior que zero"),
                          ({**ITEM, "descricao": ""}, "descreva"),
                          ({**ITEM, "uf": "ZZ"}, "ZZ")):
        with pytest.raises(cotacoes.ErroCotacao, match=motivo):
            cotacoes.salvar_item(CTX, cid, dados)


def test_u03_u04_manual_e_automatico_na_mesma_cesta(monkeypatch):
    cliente, cid, iid = _nova(monkeypatch)
    manual = cotacoes.pesquisar_item(CTX, cid, iid, modo="manual",
                                     fontes=[_fonte()])
    assert manual.unicas == 5 and manual.consideradas == 0
    assert manual.diagnostico == "amostra_insuficiente"
    linhas = repo.listar_referencias(iid)
    assert {r["status"] for r in linhas} == {"candidate"}

    escolhidas = sorted(linhas, key=lambda r: Decimal(str(
        r["valor_unitario_normalizado"])))[:3]
    revisao = int(repo.obter_item(iid)["revisao"])
    for r in escolhidas:
        cotacoes.alterar_status_referencia(
            CTX, cid, iid, str(r["id"]), incluir=True,
            motivo="mesmo produto e unidade", revisao_esperada=revisao)
        revisao += 1
    item = repo.obter_item(iid)
    assert item["estado"] == EstadoItem.EM_REVISAO.value
    assert Decimal(str(item["preco_estimado"])) == Decimal("22.00")

    auto = cotacoes.pesquisar_item(CTX, cid, iid, modo="automatico",
                                   fontes=[_fonte()])
    assert auto.preservadas == 3
    assert len(cliente.tabelas["pesquisas_preco"]) == 1, "nenhuma entidade nova"
    assert len(cliente.tabelas["pesquisa_preco_itens"]) == 1
    depois = {str(r["id"]): r["status"] for r in repo.listar_referencias(iid)}
    assert all(depois[str(r["id"])] == "selected" for r in escolhidas)
    assert sum(1 for s in depois.values() if s == "selected") == 5
    assert Decimal(str(repo.obter_item(iid)["preco_estimado"])) == Decimal("24.00")
    tipos = [e["tipo"] for e in cliente.tabelas["pesquisa_preco_eventos"]]
    assert tipos.count("busca_concluida") == 2


def test_decisao_humana_de_excluir_sobrevive_a_cotacao_automatica(monkeypatch):
    _, cid, iid = _nova(monkeypatch)
    cotacoes.pesquisar_item(CTX, cid, iid, modo="automatico", fontes=[_fonte()])
    alvo = next(r for r in repo.listar_referencias(iid)
                if Decimal(str(r["valor_unitario_normalizado"])) == Decimal("28.00"))
    cotacoes.alterar_status_referencia(CTX, cid, iid, str(alvo["id"]),
                                       incluir=False, motivo="fora da curva")
    cotacoes.pesquisar_item(CTX, cid, iid, modo="automatico", fontes=[_fonte()])
    assert next(r for r in repo.listar_referencias(iid)
                if r["id"] == alvo["id"])["status"] == "rejected"


def test_u06_fonte_fora_nao_apaga_preco_ja_coletado(monkeypatch):
    _, cid, iid = _nova(monkeypatch)
    cotacoes.pesquisar_item(CTX, cid, iid, modo="automatico", fontes=[_fonte()])
    antes = repo.listar_referencias(iid)
    falha = cotacoes.pesquisar_item(CTX, cid, iid, modo="automatico",
                                    fontes=[_fonte(explode=True)])
    assert falha.diagnostico == "fonte_indisponivel"
    assert "falha técnica" in falha.mensagem
    item = repo.obter_item(iid)
    assert item["estado"] == EstadoItem.ERRO.value
    assert repo.listar_referencias(iid) == antes


def test_inclusao_de_referencia_sem_preco_comparavel_e_recusada(monkeypatch):
    _, cid, iid = _nova(monkeypatch)
    fonte = _fonte()
    fonte._referencias[0].unidade_original = "CAIXA"   # sem fator
    cotacoes.pesquisar_item(CTX, cid, iid, modo="manual", fontes=[fonte])
    caixa = next(r for r in repo.listar_referencias(iid)
                 if r["unidade_original"] == "CAIXA")
    with pytest.raises(cotacoes.ErroCotacao, match="unidade"):
        cotacoes.alterar_status_referencia(CTX, cid, iid, str(caixa["id"]),
                                           incluir=True, motivo="quero")


def test_u07_segunda_aba_com_revisao_antiga_nao_sobrescreve(monkeypatch):
    _, cid, iid = _nova(monkeypatch)
    cotacoes.pesquisar_item(CTX, cid, iid, modo="automatico", fontes=[_fonte()])
    aba_a = aba_b = int(repo.obter_item(iid)["revisao"])
    [r1, r2, *_] = repo.listar_referencias(iid)
    cotacoes.alterar_status_referencia(CTX, cid, iid, str(r1["id"]),
                                       incluir=False, motivo="aba A",
                                       revisao_esperada=aba_a)
    preco = repo.obter_item(iid)["preco_estimado"]
    with pytest.raises(repo.ConflitoDeVersao, match="outra aba"):
        cotacoes.alterar_status_referencia(CTX, cid, iid, str(r2["id"]),
                                           incluir=False, motivo="aba B",
                                           revisao_esperada=aba_b)
    assert next(r for r in repo.listar_referencias(iid)
                if r["id"] == r2["id"])["status"] == "selected"
    assert repo.obter_item(iid)["preco_estimado"] == preco


def test_conflito_na_escrita_final_desfaz_a_mudanca(monkeypatch):
    _, cid, iid = _nova(monkeypatch)
    cotacoes.pesquisar_item(CTX, cid, iid, modo="automatico", fontes=[_fonte()])
    [r1, *_] = repo.listar_referencias(iid)
    original = repo.atualizar_estimativa

    def corrida(item, estimativa, **kw):
        repo.atualizar_item(str(item["id"]), {"quantidade": "11"},
                            revisao_esperada=int(item["revisao"]))
        return original(item, estimativa, **kw)

    monkeypatch.setattr(repo, "atualizar_estimativa", corrida)
    with pytest.raises(repo.ConflitoDeVersao):
        cotacoes.alterar_status_referencia(
            CTX, cid, iid, str(r1["id"]), incluir=False, motivo="x",
            revisao_esperada=int(repo.obter_item(iid)["revisao"]))
    linha = next(r for r in repo.listar_referencias(iid) if r["id"] == r1["id"])
    assert linha["status"] == "selected"
    assert "desfeito: conflito de versão" in " ".join(linha["motivos"])


def test_concluir_item_cotacao_e_imutabilidade(monkeypatch):
    _, cid, iid = _nova(monkeypatch)
    with pytest.raises(cotacoes.ErroCotacao, match="faltam"):
        cotacoes.concluir_cotacao(CTX, cid)
    cotacoes.pesquisar_item(CTX, cid, iid, modo="automatico", fontes=[_fonte()])
    cotacoes.concluir_item(CTX, cid, iid, justificativa="conferido na fonte")
    with pytest.raises(cotacoes.ErroCotacao, match="reabra"):
        cotacoes.pesquisar_item(CTX, cid, iid, modo="manual", fontes=[_fonte()])
    cotacoes.concluir_cotacao(CTX, cid)
    assert repo.obter_pesquisa(cid)["estado"] == "completed"
    cotacoes.arquivar(CTX, cid)
    with pytest.raises(cotacoes.CotacaoImutavel, match="revisão nova"):
        cotacoes.salvar_item(CTX, cid, ITEM)


def test_minhas_cotacoes_resume_itens_cobertura_e_valor(monkeypatch):
    _, cid, iid = _nova(monkeypatch)
    outro = cotacoes.salvar_item(CTX, cid, {**ITEM, "descricao": "CLIPS NIQUELADO"})
    cotacoes.pesquisar_item(CTX, cid, iid, modo="automatico", fontes=[_fonte()])
    cotacoes.concluir_item(CTX, cid, iid, justificativa="ok, conferido")
    cotacoes.criar_cotacao(CTX, {"nome": "Limpeza"}, idempotency_key="k2")
    [linha] = cotacoes.listar_cotacoes(CTX, busca_texto="expediente")
    assert (linha.itens, linha.com_minimo, linha.pendentes) == (2, 1, 1)
    assert linha.valor_concluidos == Decimal("240.00")
    assert linha.cobertura == 0.5
    assert len(cotacoes.listar_cotacoes(CTX)) == 2
    cotacoes.remover_item(CTX, cid, str(outro["id"]), motivo="duplicado")
    [linha] = cotacoes.listar_cotacoes(CTX, busca_texto="expediente")
    assert linha.itens == 1 and linha.pendentes == 0


def test_reordenar_preserva_numeros_e_codigos(monkeypatch):
    _, cid, iid = _nova(monkeypatch)
    b = cotacoes.salvar_item(CTX, cid, {**ITEM, "descricao": "CANETA AZUL",
                                        "unidade": "UNIDADE", "codigo": "C2"})
    cotacoes.mover_item_na_lista(CTX, cid, str(b["id"]), -1)
    ordem = [(i["descricao"], i["numero"])
             for i in cotacoes.ativos(repo.listar_itens(cid))]
    assert ordem == [("CANETA AZUL", 1), ("PAPEL SULFITE A4 75G", 2)]
    assert repo.obter_item(str(b["id"]))["codigo"] == "C2"


def test_lote_reentrante_1_e_10_itens_mesmo_contrato(monkeypatch):
    _, cid, iid = _nova(monkeypatch)
    for n in range(2, 11):
        cotacoes.salvar_item(CTX, cid, {**ITEM, "descricao": f"ITEM {n}"})
    tentados: set[str] = set()
    passos = 0
    while True:
        resultados, restantes = cotacoes.pesquisar_em_lote(
            CTX, cid, modo="automatico", tamanho=3, ja_tentados=tentados,
            fontes=[_fonte()])
        passos += 1
        if not restantes:
            break
    assert passos == 4 and len(tentados) == 10
    estados = {i["estado"] for i in repo.listar_itens(cid)}
    assert EstadoItem.PENDENTE.value not in estados
    # reexecutar não refaz nem duplica
    resultados, restantes = cotacoes.pesquisar_em_lote(
        CTX, cid, modo="automatico", tamanho=50, fontes=[_fonte()])
    assert resultados == [] and restantes == 0


def test_estado_da_cotacao_segue_os_itens(monkeypatch):
    _, cid, iid = _nova(monkeypatch)
    assert repo.obter_pesquisa(cid)["estado"] == "draft"
    cotacoes.pesquisar_item(CTX, cid, iid, modo="manual", fontes=[_fonte()])
    assert repo.obter_pesquisa(cid)["estado"] == "partial"
    cotacoes.pesquisar_item(CTX, cid, iid, modo="automatico", fontes=[_fonte()])
    assert repo.obter_pesquisa(cid)["estado"] == "review"
