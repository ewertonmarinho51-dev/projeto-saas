"""
PNCP como fonte de PREÇO pela contratação conhecida (Gate 4, 15/10/2026).

A fixture é a resposta REAL da API pública gravada em 15/10/2026
(`tests/fixtures/pncp_resultados_2026-10-15.json`, com URL e horário).
Nenhuma chamada de rede aqui.
"""

from __future__ import annotations

import json
import urllib.error
from decimal import Decimal
from pathlib import Path

import pytest

from src.precos import busca, estatistica, pncp
from src.precos.compras_gov import FONTE_PRECOS
from src.precos.fontes import Capacidade, Consulta
from src.precos.modelo import NaturezaValor, Referencia

FIXTURE = json.loads((Path(__file__).parent / "fixtures" /
                      "pncp_resultados_2026-10-15.json").read_text("utf-8"))
CONTROLE = "07954480000179-1-015836/2026"


def _api(chamadas=None, quebra=None):
    def abrir(url):
        if chamadas is not None:
            chamadas.append(url)
        if quebra and quebra in url:
            raise urllib.error.HTTPError(url, 503, "indisponível", None, None)
        if url.endswith("/compras/2026/15836"):
            return json.dumps(FIXTURE["contratacao"])
        if "/itens?" in url:
            return json.dumps(FIXTURE["itens"])
        numero = url.split("/itens/")[1].split("/")[0]
        return json.dumps(FIXTURE["resultados"][numero])
    return abrir


@pytest.mark.parametrize("entrada,esperado", [
    (CONTROLE, ("07954480000179", "2026", "15836")),
    ("https://pncp.gov.br/app/editais/07954480000179/2026/15836",
     ("07954480000179", "2026", "15836")),
    ("  07954480000179-1-015836/2026  ", ("07954480000179", "2026", "15836")),
    ("http://169.254.169.254/latest/meta-data", None),
    ("caneta azul", None),
])
def test_entrada_vira_controle_e_nunca_url_livre(entrada, esperado):
    assert pncp.controle_da_entrada(entrada) == esperado


def test_resultado_homologado_vira_referencia_de_preco():
    fonte = pncp.PNCPContratacao(CONTROLE, abrir_url=_api())
    assert Capacidade.PRECO in fonte.capacidades
    resultado = fonte.pesquisar(Consulta(descricao="PANO LIMPEZA multiuso"))
    assert resultado.falha is None
    [ref] = resultado.referencias        # itens 3 e 4: cota, contada uma vez
    assert ref.natureza_valor is NaturezaValor.HOMOLOGADO
    assert ref.valor_unitario_original == Decimal("1.96")
    assert ref.quantidade_original == Decimal("22500.0")
    assert ref.orgao == "ESTADO DO CEARA" and ref.uf == "CE"
    assert ref.referencia_externa == CONTROLE
    assert any("cota" in o for o in resultado.ocorrencias)
    assert pncp.url_de_verificacao(ref.bruto) == (
        "https://pncp.gov.br/app/editais/07954480000179/2026/15836")


def test_so_le_resultados_dos_itens_com_termos_da_descricao():
    chamadas: list[str] = []
    fonte = pncp.PNCPContratacao(CONTROLE, abrir_url=_api(chamadas))
    fonte.pesquisar(Consulta(descricao="LUSTRADOR DE MÓVEIS"))
    resultados = [u for u in chamadas if u.endswith("/resultados")]
    assert resultados == [pncp.BASE_PNCP + "/orgaos/07954480000179/compras/"
                          "2026/15836/itens/2/resultados"]


def test_total_incoerente_ou_cancelado_nao_entra():
    item = FIXTURE["itens"][0]
    linha = dict(FIXTURE["resultados"]["1"][0])
    assert pncp._referencia_do_resultado(FIXTURE["contratacao"], item, linha)
    for mudanca in ({"valorTotalHomologado": 99999.0},
                    {"dataCancelamento": "2026-09-01"},
                    {"moedaEstrangeira": True},
                    {"valorUnitarioHomologado": 0}):
        assert pncp._referencia_do_resultado(
            FIXTURE["contratacao"], item, {**linha, **mudanca}) is None


def test_queda_do_pncp_e_falha_tecnica_e_nao_mercado_vazio():
    fonte = pncp.PNCPContratacao(CONTROLE, abrir_url=_api(quebra="/itens?"))
    coleta = busca.coletar({"id": "x", "numero": 1, "descricao": "PANO LIMPEZA",
                            "unidade": "UNIDADE"}, [fonte])
    assert "falha técnica" in coleta.erro


def test_controle_invalido_falha_sem_chamar_a_rede():
    chamadas: list[str] = []
    resultado = pncp.PNCPContratacao("abc", abrir_url=_api(chamadas)).pesquisar(
        Consulta(descricao="PANO"))
    assert resultado.falha and not chamadas


def test_mesma_compra_no_compras_gov_e_no_pncp_conta_uma_vez():
    """IDX-02: duas evidências, uma observação de preço."""
    fonte = pncp.PNCPContratacao(CONTROLE, abrir_url=_api())
    [do_pncp] = fonte.pesquisar(Consulta(descricao="PANO LIMPEZA")).referencias
    do_compras = Referencia(
        fonte=FONTE_PRECOS, id_externo="cg-1",
        bruto={"idCompra": do_pncp.bruto["idCompraOrigem"]},
        descricao_original="PANO LIMPEZA", unidade_original="UN",
        valor_unitario_original=Decimal("1.96"),
        ni_fornecedor=do_pncp.ni_fornecedor,
        natureza_valor=NaturezaValor.PRATICADO)
    assert do_pncp.bruto["idCompraOrigem"] == "94300105905082026"
    ocorrencias: list[str] = []
    unicas = busca.fundir_entre_portais([do_compras, do_pncp], ocorrencias)
    assert unicas == [do_compras]
    assert any("PNCP" in m for m in do_compras.motivos)
    assert ocorrencias


def test_contratacao_importada_entra_na_cesta_pelo_pipeline_comum():
    fonte = pncp.PNCPContratacao(CONTROLE, abrir_url=_api())
    coleta = busca.coletar({"id": "x", "numero": 1,
                            "descricao": "PANO LIMPEZA", "unidade": "UNIDADE"},
                           [fonte])
    assert not coleta.erro and coleta.unicas == 1
    assert coleta.elegiveis(estatistica.PISO_COMPARABILIDADE) == 1
