"""
Política .4 da cotação automática (10/11/2026): teto de 5 e barreira do
coeficiente de variação ANTES de gravar.

O que estas provas guardam:

* toda seleção automática nova — item, lote, reexecução e rota legada —
  põe no máximo 5 referências, contando as que uma PESSOA já escolheu;
* a cesta que resultaria (de pessoa + novas) só é gravada com CV ≤ 25%,
  pelo desvio-padrão amostral em `Decimal`, comparado sem arredondar:
  75, 100 e 125 dão 25% exatos e PASSAM;
* reprovada, nada some: as novas ficam candidatas, com o motivo, o CV e a
  quantidade na referência, no item e na trilha; cesta vazia = preço
  pendente (não zero);
* série proposta com menos de dois preços não tem CV: vai para revisão;
* decisão de pessoa e histórico são preservados — inclusive mais de cinco
  escolhidas à mão, e cesta de 6 a 15 formada sob a política anterior;
* falha na LEITURA da flag do teto não desliga os limites;
* a mesma compra no Compras.gov e no PNCP conta uma vez; fonte fora não
  derruba o que a outra trouxe.

Banco falso e fontes dublês. Nada de rede nem IA.
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from src import db, governanca
from src.precos import cesta, cotacoes, estatistica, execucao
from src.precos import repositorio as repo
from src.precos.modelo import Fonte
from tests.cotacoes_apoio import (FONTE_PNCP, ligar_banco_falso, linha,
                                  referencia)
from tests.test_cotacoes_g2_servico import CTX, ITEM
from tests.test_precos_fase4 import _FonteFalsa

POL = estatistica.POLITICA_AUTOMATICA
PRECOS = Fonte("compras_gov_precos", "Compras.gov — preços praticados",
               "sistema_oficial")


def _fonte(valores, *, fonte=PRECOS, prefixo="r", explode=False):
    return _FonteFalsa(fonte, [referencia(v, f"{prefixo}{i}")
                               for i, v in enumerate(valores)],
                       explode=explode)


def _nova(monkeypatch, *, itens=1):
    ligar_banco_falso(monkeypatch)
    monkeypatch.setattr(db, "flag_ativa",
                        lambda nome: nome == governanca.FLAG_TETO_AUTOMATICO)
    c = cotacoes.criar_cotacao(CTX, {"nome": "Teto 5 e CV"})
    sufixos = ("", " BRANCO", " RECICLADO")
    ids = [str(cotacoes.salvar_item(
        CTX, str(c["id"]),
        {**ITEM, "descricao": ITEM["descricao"] + sufixos[n]})["id"])
        for n in range(itens)]
    return str(c["id"]), ids[0] if itens == 1 else ids


def _auto(cid, iid, valores, **kw):
    return cotacoes.pesquisar_item(CTX, cid, iid, modo="automatico",
                                   fontes=[_fonte(valores, **kw)])


def _busca(cid, iid=None):
    return [e["payload"] for e in repo.listar_eventos(cid)
            if e["tipo"] == "busca_concluida"
            and (iid is None or str(e.get("item_id")) == iid)]


def _incluir(cid, iid, linha):
    cotacoes.alterar_status_referencia(
        CTX, cid, iid, str(linha["id"]), incluir=True,
        motivo="mesmo produto e unidade",
        revisao_esperada=int(repo.obter_item(iid)["revisao"]))


# ---------------------------------------------------------------------------
# A regra, em unidade
# ---------------------------------------------------------------------------
def test_politica_versionada_com_teto_5():
    assert POL.teto == 5 and POL.versao == "2026-11-10.teto-5.4"
    assert POL.teto_de_emissao == 15 and POL.reserva == 10


def test_25_por_cento_exatos_passam_e_um_centavo_alem_nao():
    exato = estatistica.avaliar_barreira_cv(
        [], [Decimal("75"), Decimal("100"), Decimal("125")])
    assert exato.cv == Decimal("0.25") and exato.aprovada
    alem = estatistica.avaliar_barreira_cv(
        [], [Decimal("74.99"), Decimal("100"), Decimal("125.01")])
    assert alem.cv > Decimal("0.25") and not alem.aprovada
    assert alem.motivo == estatistica.CV_ACIMA_DO_LIMITE
    # compara ANTES de arredondar: 25,004% se exibe "25,00%" e NÃO passa
    quase = estatistica.avaliar_barreira_cv(
        [], [Decimal("7500"), Decimal("10000"), Decimal("12501")])
    assert estatistica.pct(quase.cv) == "25,00%" and not quase.aprovada


def test_cv_usa_desvio_amostral_e_soma_as_escolhas_de_pessoa():
    # (60, 100, 140): desvio amostral 40 → 40%; o populacional daria 32,66%
    b = estatistica.avaliar_barreira_cv([Decimal("100")],
                                        [Decimal("60"), Decimal("140")])
    assert b.cv == Decimal("0.4") and not b.aprovada
    assert (b.quantidade, b.preservadas, b.novas) == (3, 1, 2)


def test_menos_de_dois_precos_nao_tem_cv():
    b = estatistica.avaliar_barreira_cv([], [Decimal("10")])
    assert not b.aprovada and b.cv is None
    assert b.motivo == estatistica.CV_INDISPONIVEL
    # sem nada novo a acrescentar, a automação não tem o que barrar
    assert estatistica.avaliar_barreira_cv([Decimal("10")], []).aprovada


# ---------------------------------------------------------------------------
# Item individual
# ---------------------------------------------------------------------------
def test_mais_de_cinco_elegiveis_viram_cinco_e_reserva(monkeypatch):
    cid, iid = _nova(monkeypatch)
    r = _auto(cid, iid, [str(100 + i) for i in range(9)])
    linhas = repo.listar_referencias(iid)
    assert r.consideradas == len(cesta.consideradas(linhas)) == 5
    assert len(linhas) == 9                      # 4 de reserva, candidatas
    assert {l["status"] for l in linhas} == {"selected", "candidate"}
    assert r.politica == POL.versao
    [evento] = _busca(cid)
    assert evento["politica"] == POL.versao
    assert evento["barreira_cv"]["aprovada"] is True
    assert evento["barreira_cv"]["quantidade"] == 5
    assert "barreira_cv" not in repo.obter_item(iid)["estatisticas"]


def test_cv_de_25_exatos_grava_a_cesta(monkeypatch):
    cid, iid = _nova(monkeypatch)
    r = _auto(cid, iid, ["75", "100", "125"])
    assert r.consideradas == 3 and r.barreira_cv["cv"] == "0.25"
    item = repo.obter_item(iid)
    assert Decimal(str(item["preco_estimado"])) == Decimal("100.00")
    assert item["estado"] == "review"


def test_cv_acima_de_25_fica_para_revisao_com_motivo_cv_e_quantidade(
        monkeypatch):
    cid, iid = _nova(monkeypatch)
    r = _auto(cid, iid, ["70", "100", "130"])
    linhas = repo.listar_referencias(iid)
    assert r.consideradas == 0 and cesta.consideradas(linhas) == []
    # nada some: as três vão para "Para conferência" (manual_review), com o motivo
    assert [l["status"] for l in linhas] == ["manual_review"] * 3
    assert all(any("coeficiente de variação" in m and "30,00%" in m
                   for m in l["motivos"]) for l in linhas)
    item = repo.obter_item(iid)
    assert item["preco_estimado"] is None        # pendente, não zero
    assert item["estado"] == "incomplete"
    gravada = item["estatisticas"]["barreira_cv"]
    assert gravada["motivo"] == estatistica.CV_ACIMA_DO_LIMITE
    assert (gravada["cv"], gravada["quantidade"], gravada["novas"]) == (
        "0.3", 3, 3)
    assert any("30,00%" in p for p in item["estatisticas"]["pendencias"])
    assert "30,00%" in item["justificativa"]     # a memória vai ao relatório
    [evento] = _busca(cid)
    assert evento["barreira_cv"] == r.barreira_cv
    assert "aguardam revisão" in r.mensagem
    # o relatório (PDF/DOCX) imprime a memória e a análise crítica do item
    from src.precos import relatorio_view
    from src.precos.perfil import LEI_14133

    visao = relatorio_view._item(item, linhas, LEI_14133, ())
    assert visao.preco_unitario is None and visao.consideradas == 0
    assert any("30,00%" in p for p in visao.analise_critica)
    assert any("30,00%" in m for m in visao.memoria)


def test_uma_unica_referencia_vai_para_revisao_por_cv_indisponivel(
        monkeypatch):
    cid, iid = _nova(monkeypatch)
    r = _auto(cid, iid, ["50"])
    [linha] = repo.listar_referencias(iid)
    assert linha["status"] == "manual_review" and r.consideradas == 0
    assert r.barreira_cv["motivo"] == estatistica.CV_INDISPONIVEL
    assert r.barreira_cv["cv"] is None
    assert repo.obter_item(iid)["preco_estimado"] is None


def test_a_revisao_de_pessoa_fecha_o_item_e_tira_o_aviso(monkeypatch):
    cid, iid = _nova(monkeypatch)
    _auto(cid, iid, ["70", "100", "130"])
    for linha in repo.listar_referencias(iid):
        _incluir(cid, iid, linha)
    item = repo.obter_item(iid)
    assert Decimal(str(item["preco_estimado"])) == Decimal("100.00")
    assert item["estado"] == "review"            # o mínimo do perfil vale
    assert "barreira_cv" not in item["estatisticas"]


# ---------------------------------------------------------------------------
# Decisão manual preexistente
# ---------------------------------------------------------------------------
def test_escolha_de_pessoa_conta_na_vaga_e_no_cv(monkeypatch):
    cid, iid = _nova(monkeypatch)
    cotacoes.pesquisar_item(CTX, cid, iid, modo="manual",
                            fontes=[_fonte(["100"], prefixo="m")])
    [manual] = repo.listar_referencias(iid)
    _incluir(cid, iid, manual)
    # 100 (de pessoa) + 75 e 125 novas = 25% exatos: entra
    r = cotacoes.pesquisar_item(
        CTX, cid, iid, modo="automatico",
        fontes=[_fonte(["100"], prefixo="m"), _fonte(["75", "125"])])
    assert r.preservadas == 1 and r.consideradas == 3
    assert (r.barreira_cv["preservadas"], r.barreira_cv["novas"]) == (1, 2)


def test_cv_reprovado_preserva_a_escolha_de_pessoa(monkeypatch):
    cid, iid = _nova(monkeypatch)
    cotacoes.pesquisar_item(CTX, cid, iid, modo="manual",
                            fontes=[_fonte(["100"], prefixo="m")])
    [manual] = repo.listar_referencias(iid)
    _incluir(cid, iid, manual)
    r = cotacoes.pesquisar_item(
        CTX, cid, iid, modo="automatico",
        fontes=[_fonte(["100"], prefixo="m"), _fonte(["60", "140"])])
    por_id = {l["id_externo"]: l["status"]
              for l in repo.listar_referencias(iid)}
    assert por_id == {"m0": "selected", "r0": "manual_review", "r1": "manual_review"}
    assert r.consideradas == 1 and r.barreira_cv["cv"] == "0.4"
    item = repo.obter_item(iid)
    assert Decimal(str(item["preco_estimado"])) == Decimal("100.00")
    assert item["estatisticas"]["barreira_cv"]["novas"] == 2


def test_mais_de_cinco_escolhidas_a_mao_ficam_como_estao(monkeypatch):
    cid, iid = _nova(monkeypatch)
    valores = [str(100 + i) for i in range(8)]
    cotacoes.pesquisar_item(CTX, cid, iid, modo="manual",
                            fontes=[_fonte(valores)])
    for linha in repo.listar_referencias(iid)[:7]:
        _incluir(cid, iid, linha)
    r = _auto(cid, iid, valores)
    linhas = repo.listar_referencias(iid)
    assert len(cesta.consideradas(linhas)) == 7 and r.rebaixadas == 0
    # sem vaga, a automação não acrescenta nada — e não barra nada
    assert r.barreira_cv["aprovada"] and r.barreira_cv["novas"] == 0
    assert cesta.itens_acima_do_teto(
        [repo.obter_item(iid)], {iid: linhas}, POL.teto_de_emissao) == []


# ---------------------------------------------------------------------------
# Reexecução e lote
# ---------------------------------------------------------------------------
def test_reexecucao_nunca_passa_de_cinco(monkeypatch):
    cid, iid = _nova(monkeypatch)
    valores = [str(100 + i) for i in range(9)]
    _auto(cid, iid, valores)
    r = _auto(cid, iid, valores)
    assert r.consideradas == len(cesta.consideradas(
        repo.listar_referencias(iid))) == 5


def test_reexecucao_reprovada_rebaixa_a_selecao_antiga_da_maquina(monkeypatch):
    cid, iid = _nova(monkeypatch)
    _auto(cid, iid, ["100", "101", "102"])
    assert len(cesta.consideradas(repo.listar_referencias(iid))) == 3
    r = _auto(cid, iid, ["40", "100", "160"], prefixo="n")
    linhas = repo.listar_referencias(iid)
    assert cesta.consideradas(linhas) == [] and r.rebaixadas == 3
    assert len(linhas) == 6                      # histórico inteiro, gravado
    assert repo.obter_item(iid)["preco_estimado"] is None


def test_lote_aplica_teto_e_cv_item_a_item(monkeypatch):
    cid, (bom, disperso, unico) = _nova(monkeypatch, itens=3)
    series = {bom: [str(100 + i) for i in range(9)],
              disperso: ["70", "100", "130"], unico: ["50"]}

    class PorItem:
        fonte = PRECOS

        def pesquisar(self, consulta):
            iid = next(i for i in series
                       if repo.obter_item(i)["descricao"] == consulta.descricao)
            return _FonteFalsa(PRECOS, [
                referencia(v, f"{iid[:6]}-{n}", descricao=consulta.descricao)
                for n, v in enumerate(series[iid])]).pesquisar(consulta)

    resultados, restantes = cotacoes.pesquisar_em_lote(
        CTX, cid, modo="automatico", tamanho=10, fontes=[PorItem()])
    assert restantes == 0 and len(resultados) == 3
    por_item = {r.item_id: r for r in resultados}
    assert por_item[bom].consideradas == 5
    assert por_item[disperso].consideradas == 0
    assert por_item[disperso].barreira_cv["motivo"] == \
        estatistica.CV_ACIMA_DO_LIMITE
    assert por_item[unico].barreira_cv["motivo"] == estatistica.CV_INDISPONIVEL
    for iid in (bom, disperso, unico):
        assert len(cesta.consideradas(repo.listar_referencias(iid))) <= POL.teto


# ---------------------------------------------------------------------------
# Flag, fontes e histórico
# ---------------------------------------------------------------------------
def test_falha_na_leitura_da_flag_nao_desliga_os_limites(monkeypatch):
    cid, iid = _nova(monkeypatch)

    def quebrada(nome):
        raise db.ErroBanco("flags indisponíveis")

    monkeypatch.setattr(db, "flag_ativa", quebrada)
    r = _auto(cid, iid, [str(100 + i) for i in range(9)])
    assert r.politica == POL.versao and r.consideradas == 5


def test_flag_lida_e_desligada_continua_sendo_o_rollback(monkeypatch):
    cid, iid = _nova(monkeypatch)
    monkeypatch.setattr(db, "flag_ativa", lambda nome: False)
    r = _auto(cid, iid, ["70", "100", "130", "101", "102", "103", "104"])
    assert r.politica == "" and r.consideradas == 7 and not r.barreira_cv


def test_mesma_compra_no_compras_gov_e_no_pncp_conta_uma_vez(monkeypatch):
    cid, iid = _nova(monkeypatch)

    def par(fonte, ident, chave_do_bruto):
        ref = referencia("100", ident, fonte=fonte)
        ref.ni_fornecedor = "12345678000190"
        ref.bruto = {chave_do_bruto: "94300105905082026"}
        return ref

    compras = _FonteFalsa(PRECOS, [par(PRECOS, "cg-1", "idCompra"),
                                   referencia("98", "cg-2"),
                                   referencia("102", "cg-3")])
    pncp = _FonteFalsa(FONTE_PNCP, [par(FONTE_PNCP, "pn-1", "idCompraOrigem")])
    r = cotacoes.pesquisar_item(CTX, cid, iid, modo="automatico",
                                fontes=[compras, pncp])
    assert (r.brutas, r.unicas, r.consideradas) == (4, 3, 3)
    linhas = repo.listar_referencias(iid)
    assert {l["fonte_id"] for l in linhas} == {"compras_gov_precos"}
    assert any("mesma compra" in m for l in linhas for m in l["motivos"])


def test_falha_parcial_preserva_o_que_a_outra_fonte_trouxe(monkeypatch):
    cid, iid = _nova(monkeypatch)
    fora = _fonte(["1"], explode=True)
    de_pe = _fonte(["100", "101", "102"], fonte=FONTE_PNCP, prefixo="p")
    r = cotacoes.pesquisar_item(CTX, cid, iid, modo="automatico",
                                fontes=[fora, de_pe])
    assert r.diagnostico == "ok" and r.consideradas == 3
    assert r.desfechos["compras_gov_precos"] == "failure"
    assert r.desfechos["pncp"] == "success_with_prices"


def test_cesta_de_6_a_15_da_politica_anterior_segue_emitivel():
    def item_com(n):
        linhas = [linha(100 + i, ident=f"e{i}", item_id="i1")
                  for i in range(n)]
        return [{"id": "i1", "numero": 1}], {"i1": linhas}

    assert cesta.itens_acima_do_teto(*item_com(15), POL.teto_de_emissao) == []
    assert cesta.itens_acima_do_teto(*item_com(16), POL.teto_de_emissao)


# ---------------------------------------------------------------------------
# Rota legada — a mesma barreira
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("valores,na_cesta,motivo", [
    ([str(100 + i) for i in range(9)], 5, ""),
    (["75", "100", "125"], 3, ""),
    (["70", "100", "130"], 0, estatistica.CV_ACIMA_DO_LIMITE),
    (["50"], 0, estatistica.CV_INDISPONIVEL),
])
def test_rota_legada_obedece_teto_e_cv(valores, na_cesta, motivo):
    item = {"id": "i1", "numero": 1, **ITEM}
    r = execucao.pesquisar_item(item, [_fonte(valores)], politica=POL)
    assert len(r.estimativa.cesta.selecionadas) == na_cesta
    assert (r.estimativa.barreira_cv or {}).get("motivo", "") == motivo
    if motivo:
        assert r.estimativa.valor_unitario is None
        assert len(r.referencias) == len(valores)      # gravadas, para conferência
        assert all(ref.status.value == "manual_review" for ref, _ in r.referencias)
