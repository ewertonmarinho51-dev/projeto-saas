"""
G1 (pacote de 17/10/2026) — teto de 15 referências na cotação automática.

Medido antes: 301 candidatas por fonte → 602 referências gravadas e 452
CONSIDERADAS por item. O que estas provas guardam:

* a cesta automática de um item tem no máximo 15 referências — inclusive
  numa reconsulta, contando as que já estavam lá;
* 15 é teto, não meta: com 3 boas, ficam 3;
* a seleção é por prioridade de fonte e comparabilidade, nunca "as
  primeiras" nem "as mais baratas";
* a busca para de consultar fontes quando a amostra já basta — reduz
  chamada, não só corta a lista depois;
* só se grava a cesta, o já decidido e uma reserva para o revisor;
* decisão humana não é desfeita; desconsiderada não volta;
* modo manual e flag desligada: exatamente como antes.

Fontes dublês do benchmark (`scripts/benchmark_cotacoes.FonteSintetica`),
banco falso das provas. Nada de rede nem IA.
"""

from __future__ import annotations

import sys
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


def _ranqueadas(n: int, *, tipo="sistema_oficial"):
    """n elegíveis com comparabilidade decrescente e preço CRESCENTE."""
    fonte = Fonte("compras_gov_precos", "Compras.gov", tipo)
    saida = []
    for i in range(n):
        ref = Referencia(
            fonte=fonte, id_externo=f"r{i}", bruto={"i": i},
            descricao_original="papel", unidade_original="RESMA",
            valor_unitario_original=Decimal(20 + i),
            natureza_valor=NaturezaValor.HOMOLOGADO)
        ref.unidade_normalizada = "RESMA"
        ref.valor_unitario_normalizado = Decimal(20 + i)
        score = Decimal("0.99") - Decimal(i) / Decimal(1000)
        saida.append((ref, Comparabilidade(score=score, fatores={})))
    return saida


# ---------------------------------------------------------------------------
# Unidade — a regra da cesta
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("n", [0, 1, 2, 3, 5, 15, 16, 100, 300])
def test_teto_nunca_passa_de_15_e_nao_infla(n):
    cesta_ = estatistica.selecionar_cesta(_ranqueadas(n), teto=POL.teto)
    assert len(cesta_.selecionadas) == min(n, 15)
    assert len(cesta_.excedentes) == max(0, n - 15)
    for ref in cesta_.excedentes:
        assert ref.status.value == "candidate"
        assert any("teto" in m for m in ref.motivos)


def test_sem_teto_e_o_comportamento_historico():
    cesta_ = estatistica.selecionar_cesta(_ranqueadas(300))
    assert len(cesta_.selecionadas) == 300 and not cesta_.excedentes


def test_ficam_as_mais_comparaveis_nao_as_mais_baratas():
    pares = list(reversed(_ranqueadas(40)))      # ordem de entrada invertida
    cesta_ = estatistica.selecionar_cesta(pares, teto=15)
    ids = {r.id_externo for r in cesta_.selecionadas}
    assert ids == {f"r{i}" for i in range(15)}   # maiores scores


def test_mesma_aritmetica_decimal_sobre_a_cesta_escolhida():
    cesta_ = estatistica.selecionar_cesta(_ranqueadas(40), teto=15)
    est = estatistica.estimar(cesta_, regras=estatistica.REGRAS_MEDIA_PADRAO)
    esperado = sum(Decimal(20 + i) for i in range(15)) / 15
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


def test_301_por_fonte_vira_no_maximo_15_e_para_na_primeira_fonte(monkeypatch):
    cid, iid = _nova(monkeypatch)
    fontes = _fontes(301)
    r = cotacoes.pesquisar_item(CTX, cid, iid, modo="automatico",
                                fontes=fontes)
    linhas = repo.listar_referencias(iid)
    assert r.consideradas == len(cesta.consideradas(linhas)) == 15
    assert len(linhas) <= POL.teto + POL.reserva
    assert r.nao_gravadas > 200 and r.brutas == 301
    assert fontes[0].chamadas == 1 and fontes[1].chamadas == 0
    assert r.fontes_nao_consultadas and r.politica == POL.versao
    [evento] = [e for e in repo.listar_eventos(cid)
                if e["tipo"] == "busca_concluida"]
    assert evento["payload"]["politica"] == POL.versao
    assert evento["payload"]["nao_gravadas"] == r.nao_gravadas
    assert evento["payload"]["brutas"] == 301       # a trilha não finge


def test_com_poucas_boas_nao_infla_e_consulta_a_proxima_fonte(monkeypatch):
    cid, iid = _nova(monkeypatch)
    fontes = _fontes(3)       # 3 por fonte, 1 vizinha: abaixo do suficiente
    r = cotacoes.pesquisar_item(CTX, cid, iid, modo="automatico",
                                fontes=fontes)
    assert fontes[1].chamadas == 1                  # ampliou: não bastava
    assert r.consideradas <= 6 and not r.fontes_nao_consultadas


def test_fonte_principal_fora_consulta_a_seguinte(monkeypatch):
    cid, iid = _nova(monkeypatch)
    fora = FonteSintetica(volume=301)
    fora.pesquisar = lambda consulta: (_ for _ in ()).throw(
        RuntimeError("HTTP 503"))
    reserva = FonteSintetica(volume=301, fonte_id="pncp")
    reserva.registrar({**ITEM, "numero": 1, "valor_unitario": 28.7})
    r = cotacoes.pesquisar_item(CTX, cid, iid, modo="automatico",
                                fontes=[fora, reserva])
    assert reserva.chamadas == 1 and r.consideradas == 15
    assert r.diagnostico == "ok"


@pytest.mark.parametrize("ja_na_cesta", [14, 15])
def test_reconsulta_nunca_poe_a_16a(monkeypatch, ja_na_cesta):
    cid, iid = _nova(monkeypatch)
    cotacoes.pesquisar_item(CTX, cid, iid, modo="automatico",
                            fontes=_fontes(301))
    linhas = repo.listar_referencias(iid)
    dentro = cesta.consideradas(linhas)
    # o revisor tira algumas: a cesta fica com `ja_na_cesta`
    for linha in dentro[ja_na_cesta:]:
        repo.reclassificar_referencia(str(linha["id"]), "rejected",
                                      "fora da curva")
    r = cotacoes.pesquisar_item(CTX, cid, iid, modo="automatico",
                                fontes=_fontes(301))
    final = repo.listar_referencias(iid)
    assert len(cesta.consideradas(final)) <= 15 and r.consideradas <= 15
    rejeitadas = {l["id_externo"] for l in final if l["status"] == "rejected"}
    assert len(rejeitadas) == 15 - ja_na_cesta     # desconsiderada não volta


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
    assert len(com.estimativa.cesta.selecionadas) == 15
    assert len(com.referencias) <= POL.teto + POL.reserva
    assert fontes[1].chamadas == 0
