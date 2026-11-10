"""
G1 (pacote de 17/10/2026) — teto de 5 referências na cotação automática.

Medido antes: 301 candidatas por fonte → 602 referências gravadas e 452
CONSIDERADAS por item. O que estas provas guardam:

* a cesta automática de um item tem no máximo 5 referências — inclusive
  numa reconsulta, contando as que já estavam lá;
* 5 é teto, não meta: com 3 boas, ficam 3;
* a seleção é por prioridade de fonte e comparabilidade, nunca "as
  primeiras" nem "as mais baratas";
* TODA fonte é consultada, mesmo com amostra farta na primeira, e as
  vagas da cesta são repartidas entre as fontes (21/10/2026 — a .2
  parava no primeiro portal e a cesta saía de um portal só);
* só se grava a cesta, o já decidido e uma reserva para o revisor;
* decisão humana não é desfeita; desconsiderada não volta;
* modo manual e flag desligada: exatamente como antes.

Fontes dublês do benchmark (`scripts/benchmark_cotacoes.FonteSintetica`),
banco falso das provas. Nada de rede nem IA.
"""

from __future__ import annotations

import sys
from collections import Counter
from decimal import Decimal
from pathlib import Path

import pytest

from src import db, governanca
from src.precos import cesta, cotacoes, estatistica, execucao
from src.precos import repositorio as repo
from src.precos.matching import Comparabilidade
from src.precos.modelo import Fonte, NaturezaValor, Referencia
from tests.cotacoes_apoio import ligar_banco_falso
from tests.test_cotacoes_g2_servico import CTX

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from benchmark_cotacoes import FonteSintetica  # noqa: E402

POL = estatistica.POLITICA_AUTOMATICA
ITEM = {"descricao": "PAPEL SULFITE A4 75G RESMA 500 FOLHAS",
        "unidade": "RESMA", "quantidade": "10"}


def _ranqueadas(n: int, *, tipo="sistema_oficial",
                fonte_id="compras_gov_precos", prefixo="r",
                score_base=Decimal("0.99")):
    """n elegíveis com comparabilidade decrescente e preço CRESCENTE."""
    fonte = Fonte(fonte_id, fonte_id, tipo)
    saida = []
    for i in range(n):
        ref = Referencia(
            fonte=fonte, id_externo=f"{prefixo}{i}", bruto={"i": i},
            descricao_original="papel", unidade_original="RESMA",
            valor_unitario_original=Decimal(20 + i),
            natureza_valor=NaturezaValor.HOMOLOGADO)
        ref.unidade_normalizada = "RESMA"
        ref.valor_unitario_normalizado = Decimal(20 + i)
        score = score_base - Decimal(i) / Decimal(1000)
        saida.append((ref, Comparabilidade(score=score, fatores={})))
    return saida


# ---------------------------------------------------------------------------
# Unidade — a regra da cesta
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("n", [0, 1, 2, 3, 5, 6, 15, 100, 300])
def test_teto_nunca_passa_de_5_e_nao_infla(n):
    cesta_ = estatistica.selecionar_cesta(_ranqueadas(n), teto=POL.teto)
    assert len(cesta_.selecionadas) == min(n, POL.teto)
    assert len(cesta_.excedentes) == max(0, n - POL.teto)
    for ref in cesta_.excedentes:
        assert ref.status.value == "candidate"
        assert any("teto" in m for m in ref.motivos)


def test_sem_teto_e_o_comportamento_historico():
    cesta_ = estatistica.selecionar_cesta(_ranqueadas(300))
    assert len(cesta_.selecionadas) == 300 and not cesta_.excedentes


def test_ficam_as_mais_comparaveis_nao_as_mais_baratas():
    pares = list(reversed(_ranqueadas(40)))      # ordem de entrada invertida
    cesta_ = estatistica.selecionar_cesta(pares, teto=POL.teto)
    ids = {r.id_externo for r in cesta_.selecionadas}
    assert ids == {f"r{i}" for i in range(POL.teto)}   # maiores scores


def test_teto_reparte_as_vagas_entre_as_fontes():
    pares = (_ranqueadas(40, fonte_id="compras_gov_precos", prefixo="a")
             + _ranqueadas(40, fonte_id="pncp", prefixo="b",
                           tipo="contratacao_similar")
             + _ranqueadas(1, fonte_id="tce_rs", prefixo="c", tipo="outro",
                           score_base=Decimal("0.80")))
    cesta_ = estatistica.selecionar_cesta(pares, teto=POL.teto)
    por_fonte = Counter(r.fonte.id for r in cesta_.selecionadas)
    # rodízio: 5 rodadas de 3 fontes; a fonte de UMA referência entra
    assert por_fonte == {"compras_gov_precos": 2, "pncp": 2, "tce_rs": 1}
    # dentro de cada fonte, continuam as mais comparáveis
    assert {r.id_externo for r in cesta_.selecionadas
            if r.fonte.id == "pncp"} == {f"b{i}" for i in range(2)}
    # a de maior prioridade normativa abre cada rodada
    assert cesta_.selecionadas[0].fonte.id == "compras_gov_precos"
    assert len(cesta_.excedentes) == 81 - POL.teto


def test_teto_com_fonte_de_baixa_prioridade_mais_comparavel():
    # prioridade normativa decide quem abre a rodada, não o score
    pares = (_ranqueadas(10, fonte_id="sites", prefixo="s", tipo="outro")
             + _ranqueadas(10, fonte_id="compras_gov_precos", prefixo="g",
                           score_base=Decimal("0.70")))
    cesta_ = estatistica.selecionar_cesta(pares, teto=3)
    assert [r.fonte.id for r in cesta_.selecionadas] == [
        "compras_gov_precos", "sites", "compras_gov_precos"]


def test_rodizio_so_com_teto_sem_teto_e_a_ordem_historica():
    def pares():
        return (_ranqueadas(3, fonte_id="compras_gov_precos", prefixo="a")
                + _ranqueadas(3, fonte_id="pncp", prefixo="b",
                              score_base=Decimal("0.90")))
    sem = estatistica.selecionar_cesta(pares())
    com = estatistica.selecionar_cesta(pares(), teto=6)
    assert [r.id_externo for r in sem.selecionadas] == [
        "a0", "a1", "a2", "b0", "b1", "b2"]
    assert [r.id_externo for r in com.selecionadas] == [
        "a0", "b0", "a1", "b1", "a2", "b2"]


def test_mesma_aritmetica_decimal_sobre_a_cesta_escolhida():
    cesta_ = estatistica.selecionar_cesta(_ranqueadas(40), teto=POL.teto)
    est = estatistica.estimar(cesta_, regras=estatistica.REGRAS_MEDIA_PADRAO)
    esperado = sum(Decimal(20 + i) for i in range(POL.teto)) / 15
    assert est.estatisticas.media == esperado


# ---------------------------------------------------------------------------
# Cotação unificada — serviço, com o banco falso
# ---------------------------------------------------------------------------
def _ligar(monkeypatch, *, teto: bool):
    ligar_banco_falso(monkeypatch)
    ligadas = {governanca.FLAG_TETO_AUTOMATICO} if teto else set()
    monkeypatch.setattr(db, "flag_ativa", lambda nome: nome in ligadas)


def _fontes(volume: int, *, duas=True, numero=1):
    fontes = [FonteSintetica(volume=volume)]
    if duas:
        fontes.append(FonteSintetica(volume=volume, fonte_id="pncp"))
    for f in fontes:
        f.registrar({**ITEM, "numero": numero, "valor_unitario": 28.7})
    return fontes


def _nova(monkeypatch, *, teto=True):
    _ligar(monkeypatch, teto=teto)
    c = cotacoes.criar_cotacao(CTX, {"nome": "Teto"})
    item = cotacoes.salvar_item(CTX, str(c["id"]), ITEM)
    return str(c["id"]), str(item["id"])


def test_301_por_fonte_vira_no_maximo_15_de_todas_as_fontes(monkeypatch):
    cid, iid = _nova(monkeypatch)
    fontes = _fontes(301)
    r = cotacoes.pesquisar_item(CTX, cid, iid, modo="automatico",
                                fontes=fontes)
    linhas = repo.listar_referencias(iid)
    dentro = cesta.consideradas(linhas)
    assert r.consideradas == len(dentro) == POL.teto
    assert len(linhas) <= POL.teto + POL.reserva
    assert r.nao_gravadas > 200 and r.brutas == 602
    # amostra farta na primeira NÃO dispensa a segunda
    assert fontes[0].chamadas == 1 and fontes[1].chamadas == 1
    por_fonte = Counter(l["fonte_id"] for l in dentro)
    assert sorted(por_fonte.values()) == [2, 3], por_fonte
    assert r.politica == POL.versao
    [evento] = [e for e in repo.listar_eventos(cid)
                if e["tipo"] == "busca_concluida"]
    assert evento["payload"]["politica"] == POL.versao
    assert evento["payload"]["nao_gravadas"] == r.nao_gravadas
    assert evento["payload"]["brutas"] == 602       # a trilha não finge


def test_com_poucas_boas_nao_infla_e_consulta_a_proxima_fonte(monkeypatch):
    cid, iid = _nova(monkeypatch)
    fontes = _fontes(3)       # 3 por fonte, 1 vizinha: poucas boas
    r = cotacoes.pesquisar_item(CTX, cid, iid, modo="automatico",
                                fontes=fontes)
    assert fontes[1].chamadas == 1
    assert r.consideradas <= 6


def test_fonte_principal_fora_consulta_a_seguinte(monkeypatch):
    cid, iid = _nova(monkeypatch)
    fora = FonteSintetica(volume=301)
    fora.pesquisar = lambda consulta: (_ for _ in ()).throw(
        RuntimeError("HTTP 503"))
    reserva = FonteSintetica(volume=301, fonte_id="pncp")
    reserva.registrar({**ITEM, "numero": 1, "valor_unitario": 28.7})
    r = cotacoes.pesquisar_item(CTX, cid, iid, modo="automatico",
                                fontes=[fora, reserva])
    assert reserva.chamadas == 1 and r.consideradas == POL.teto
    assert r.diagnostico == "ok"


@pytest.mark.parametrize("ja_na_cesta", [4, 5])
def test_reconsulta_nunca_poe_a_6a(monkeypatch, ja_na_cesta):
    cid, iid = _nova(monkeypatch)
    cotacoes.pesquisar_item(CTX, cid, iid, modo="automatico",
                            fontes=_fontes(301))
    linhas = repo.listar_referencias(iid)
    dentro = cesta.consideradas(linhas)
    # o revisor tira algumas PELA TELA (com evento): fica com `ja_na_cesta`
    for linha in dentro[ja_na_cesta:]:
        cotacoes.alterar_status_referencia(
            CTX, cid, iid, str(linha["id"]), incluir=False,
            motivo="fora da curva",
            revisao_esperada=int(repo.obter_item(iid)["revisao"]))
    r = cotacoes.pesquisar_item(CTX, cid, iid, modo="automatico",
                                fontes=_fontes(301))
    final = repo.listar_referencias(iid)
    assert len(cesta.consideradas(final)) <= POL.teto and r.consideradas <= POL.teto
    rejeitadas = {l["id_externo"] for l in final if l["status"] == "rejected"}
    assert len(rejeitadas) == POL.teto - ja_na_cesta     # desconsiderada não volta


def test_modo_manual_nao_tem_teto(monkeypatch):
    cid, iid = _nova(monkeypatch)
    fontes = _fontes(301)
    cotacoes.pesquisar_item(CTX, cid, iid, modo="manual", fontes=fontes)
    linhas = repo.listar_referencias(iid)
    assert len(linhas) == 602 and fontes[1].chamadas == 1
    assert {l["status"] for l in linhas} == {"candidate"}


def test_flag_desligada_e_o_comportamento_anterior(monkeypatch):
    cid, iid = _nova(monkeypatch, teto=False)
    r = cotacoes.pesquisar_item(CTX, cid, iid, modo="automatico",
                                fontes=_fontes(301))
    assert r.politica == "" and r.nao_gravadas == 0
    assert len(repo.listar_referencias(iid)) == 602
    assert r.consideradas == 452


def test_jev_recebe_so_o_gravado(monkeypatch):
    cid, iid = _nova(monkeypatch)
    vistas = []
    cotacoes.pesquisar_item(
        CTX, cid, iid, modo="automatico", fontes=_fontes(301),
        seletor=lambda cotacao, item, linhas: vistas.append(len(linhas)))
    assert vistas == [len(repo.listar_referencias(iid))]
    assert vistas[0] <= POL.teto + POL.reserva


# ---------------------------------------------------------------------------
# Rota legada — mesma política
# ---------------------------------------------------------------------------
def test_rota_legada_respeita_o_mesmo_teto():
    fontes = _fontes(301)
    item = {"id": "i1", "numero": 1, **ITEM}
    sem = execucao.pesquisar_item(item, _fontes(301))
    com = execucao.pesquisar_item(item, fontes, politica=POL)
    assert len(sem.estimativa.cesta.selecionadas) == 452
    assert len(com.estimativa.cesta.selecionadas) == POL.teto
    assert len(com.referencias) <= POL.teto + POL.reserva
    assert fontes[1].chamadas == 1
    assert {r.fonte.id for r in com.estimativa.cesta.selecionadas} == {
        "compras_gov_precos", "pncp"}


# ---------------------------------------------------------------------------
# Correção de 17/10/2026 (medido em produção com o teto ligado: cestas de
# 65, 258 e 24 referências — seleções da automática ANTERIORES ao teto
# eram tratadas como decisão humana; e 500 a 611 registros brutos por
# item, porque o grupo do catálogo pedia 500)
# ---------------------------------------------------------------------------
def _cotacao_antiga_sem_teto(monkeypatch):
    """Item pesquisado ANTES do teto: 452 na cesta, feitas pela máquina."""
    cid, iid = _nova(monkeypatch, teto=False)
    cotacoes.pesquisar_item(CTX, cid, iid, modo="automatico",
                            fontes=_fontes(301))
    assert len(cesta.consideradas(repo.listar_referencias(iid))) == 452
    ligadas = {governanca.FLAG_TETO_AUTOMATICO}
    monkeypatch.setattr(db, "flag_ativa", lambda nome: nome in ligadas)
    return cid, iid


def test_rodada_com_teto_reavalia_selecoes_antigas_da_maquina(monkeypatch):
    cid, iid = _cotacao_antiga_sem_teto(monkeypatch)
    antes = len(repo.listar_referencias(iid))
    r = cotacoes.pesquisar_item(CTX, cid, iid, modo="automatico",
                                fontes=_fontes(301))
    linhas = repo.listar_referencias(iid)
    assert len(cesta.consideradas(linhas)) == r.consideradas == POL.teto
    assert len(linhas) == antes                # nada apagado
    # as seleções antigas saem da cesta: em lote (`rebaixadas`) ou pelo
    # upsert da reserva do revisor
    assert r.rebaixadas >= 452 - POL.teto - POL.reserva
    [evento] = [e for e in repo.listar_eventos(cid)
                if e["tipo"] == "busca_concluida"
                and (e["payload"] or {}).get("politica")]
    assert evento["payload"]["rebaixadas"] == r.rebaixadas


def test_decisao_de_pessoa_sobrevive_a_reavaliacao(monkeypatch):
    cid, iid = _cotacao_antiga_sem_teto(monkeypatch)
    linhas = repo.listar_referencias(iid)
    dentro = cesta.consideradas(linhas)
    escolhida, excluida = dentro[-1], dentro[-2]
    revisao = int(repo.obter_item(iid)["revisao"])
    # o revisor exclui uma e tira-e-repõe outra (inclusão com motivo)
    cotacoes.alterar_status_referencia(CTX, cid, iid, str(excluida["id"]),
                                       incluir=False, motivo="fora da curva",
                                       revisao_esperada=revisao)
    revisao = int(repo.obter_item(iid)["revisao"])
    cotacoes.alterar_status_referencia(CTX, cid, iid, str(escolhida["id"]),
                                       incluir=True, motivo="mesmo produto",
                                       revisao_esperada=revisao)
    cotacoes.pesquisar_item(CTX, cid, iid, modo="automatico",
                            fontes=_fontes(301))
    final = {l["id"]: l for l in repo.listar_referencias(iid)}
    assert final[excluida["id"]]["status"] == "rejected"
    assert final[escolhida["id"]]["status"] == "selected"
    assert len(cesta.consideradas(list(final.values()))) <= POL.teto


def test_ia_ve_so_o_que_decide_o_item(monkeypatch):
    cid, iid = _cotacao_antiga_sem_teto(monkeypatch)
    vistas = []
    cotacoes.pesquisar_item(
        CTX, cid, iid, modo="automatico", fontes=_fontes(301),
        seletor=lambda cotacao, item, linhas: vistas.append(len(linhas)))
    assert vistas and vistas[0] <= POL.teto + POL.reserva


def test_grupo_do_catalogo_menor_na_automatica_e_inteiro_no_manual(monkeypatch):
    vistos = {}

    class Espia(FonteSintetica):
        def pesquisar(self, consulta):
            vistos[self._modo] = consulta.limite_grupo
            return super().pesquisar(consulta)

    for modo in ("automatico", "manual"):
        cid, iid = _nova(monkeypatch)
        espia = Espia(volume=6)
        espia._modo = modo
        espia.registrar({**ITEM, "numero": 1, "valor_unitario": 28.7})
        cotacoes.pesquisar_item(CTX, cid, iid, modo=modo, fontes=[espia])
    assert vistos == {"automatico": POL.limite_por_grupo, "manual": 500}


def test_adapter_compras_gov_pede_o_grupo_pelo_limite_da_consulta():
    from src.precos.compras_gov import ComprasGovAdapter
    from src.precos.fontes import Consulta, ResultadoBusca

    pedidos = []
    adapter = ComprasGovAdapter(abrir_url=lambda *a, **k: None)
    adapter._obter = lambda caminho, params, resultado: (
        pedidos.append(params["tamanhoPagina"]) or None)
    for limite_grupo in (100, 500):
        adapter._por_pdm(Consulta(descricao="papel", limite_grupo=limite_grupo),
                         "123", ResultadoBusca(fonte=adapter.fonte))
    assert pedidos == [100, 500]


# ---------------------------------------------------------------------------
# Regra de produção (09/11/2026): 5 referências + CV estritamente acima
# de 25% impede somente a inclusão AUTOMÁTICA; nada é apagado.
# ---------------------------------------------------------------------------
def _com_precos(valores):
    pares = _ranqueadas(len(valores))
    for (ref, _), valor in zip(pares, valores):
        ref.valor_unitario_normalizado = Decimal(str(valor))
    return pares


def test_cv_acima_de_25_bloqueia_toda_a_inclusao_automatica():
    escolha = estatistica.selecionar_cesta(
        _com_precos([10, 10, 10, 10, 100]), teto=POL.teto,
        cv_maximo=POL.cv_maximo)
    assert escolha.selecionadas == []
    assert len(escolha.retidas) == POL.teto
    assert all(r.status.value == "candidate" for r in escolha.retidas)
    assert all(any("coeficiente de variação" in m for m in r.motivos)
               for r in escolha.retidas)
    assert any("25,00%" in m for m in escolha.motivos)
    assert not estatistica.estimar(escolha).concluida


def test_cv_exatamente_25_permite_selecao():
    # Média 100, desvio amostral 25: CV exatamente 25%.
    escolha = estatistica.selecionar_cesta(
        _com_precos([75, 100, 125]), teto=POL.teto,
        cv_maximo=POL.cv_maximo)
    assert len(escolha.selecionadas) == 3
    assert escolha.retidas == []


def test_cv_com_uma_referencia_nao_finge_dispersao():
    escolha = estatistica.selecionar_cesta(
        _com_precos([100]), teto=POL.teto,
        cv_maximo=POL.cv_maximo)
    assert len(escolha.selecionadas) == 1


def test_cv_e_calculado_com_precos_preservados_de_pessoa():
    escolha = estatistica.selecionar_cesta(
        _com_precos([10, 10, 10, 10]), teto=4,
        cv_maximo=POL.cv_maximo,
        valores_ja_considerados=[Decimal("100")])
    assert not escolha.selecionadas
    assert len(escolha.retidas) == 4


def test_modo_sem_politica_nao_remove_decisao_manual():
    escolha = estatistica.selecionar_cesta(
        _com_precos([10, 10, 10, 10, 100]))
    assert len(escolha.selecionadas) == 5
    assert not escolha.retidas


def test_servico_registra_bloqueio_cv_sem_perder_referencias(monkeypatch):
    cid, iid = _nova(monkeypatch)
    # Duas fontes; a série altamente dispersa não pode virar cesta.
    class FonteDispersa:
        def __init__(self):
            self.fonte = Fonte("dispersa", "Dispersa (teste)", "sistema_oficial")
        def pesquisar(self, consulta):
            from src.precos.fontes import ResultadoBusca
            referencias = []
            for i, valor in enumerate([10, 10, 10, 10, 100]):
                ref = Referencia(
                    fonte=self.fonte, id_externo=f"d-{i}",
                    bruto={"valor": str(valor)},
                    descricao_original=consulta.descricao,
                    unidade_original="RESMA",
                    valor_unitario_original=Decimal(valor),
                    natureza_valor=NaturezaValor.HOMOLOGADO)
                referencias.append(ref)
            return ResultadoBusca(fonte=self.fonte, referencias=referencias)
    r = cotacoes.pesquisar_item(
        CTX, cid, iid, modo="automatico", fontes=[FonteDispersa()])
    assert r.consideradas == 0
    assert any("coeficiente de variação" in m for m in r.ocorrencias)
    gravadas = repo.listar_referencias(iid)
    assert len(gravadas) == 5
    assert not cesta.consideradas(gravadas)
