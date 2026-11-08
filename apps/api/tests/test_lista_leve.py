"""
A lista lê só o que o resumo usa e chega à MESMA resposta.

`_COLUNAS_DO_RESUMO` existe para não trazer o texto dos documentos. O risco de
recortar é o resumo passar a ler um campo que o recorte não traz e errar o status
em silêncio: por isso a prova compara a linha inteira com a leve, caso a caso, e
confere que o recorte não pede `dados` nem `documentos` inteiros.
"""

from __future__ import annotations

import pytest

from govconect_api.processos import _COLUNAS_DO_RESUMO, _para_contrato
from src.config import CHAVE_FLUXO_MAPA


def _inteira(**campos):
    base = {"id": "p", "nome": "", "orgao": "Saúde", "objeto": "Luvas", "etapa": 1,
            "dados": {}, "documentos": {}, "aprovados": [],
            "criado_em": "2026-11-01T10:00:00+00:00", "atualizado_em": "2026-11-01T10:00:00+00:00"}
    return {**base, **campos}


def _como_o_postgrest_devolve(linha: dict) -> dict:
    """O que a leitura de `_COLUNAS_DO_RESUMO` traz para esta linha."""
    dados = linha["dados"]
    itens = dados.get("itens") or []
    leve = {k: v for k, v in linha.items() if k not in ("dados", "documentos")}
    return {**leve,
            "documentos_gerados": sorted(linha["documentos"]),
            "fluxo_com_mapa": dados.get(CHAVE_FLUXO_MAPA),
            "modelo_execucao": dados.get("modelo_execucao"),
            "pesquisa_preco_id": dados.get("pesquisa_preco_id"),
            "primeiro_item": itens[0] if itens else None}


TEXTO = "## Texto longo do documento " * 200
ITENS = [{"descricao": "Papel A4", "quantidade": 10}]

CASOS = {
    "vazio": {},
    "nome proprio": {"nome": "Compra de papel"},
    "documento gerado, sem aprovar": {"documentos": {"dfd": TEXTO}},
    "dfd aprovado": {"documentos": {"dfd": TEXTO}, "aprovados": ["dfd"]},
    "aguardando precos": {"dados": {"itens": ITENS}, "documentos": {"dfd": TEXTO}, "aprovados": ["dfd"]},
    "pesquisa ja aplicada": {"dados": {"itens": ITENS, "pesquisa_preco_id": "x"},
                             "documentos": {"dfd": TEXTO}, "aprovados": ["dfd"]},
    "lista de itens vazia": {"dados": {"itens": []}, "documentos": {"dfd": TEXTO}, "aprovados": ["dfd"]},
    "fluxo com mapa pela chave": {"dados": {CHAVE_FLUXO_MAPA: True}},
    "fluxo com mapa pelo documento": {"documentos": {"mapa_riscos": TEXTO, "dfd": TEXTO, "etp": TEXTO},
                                      "aprovados": ["dfd", "etp"]},
    "registro de precos": {"dados": {"modelo_execucao": "Sistema de Registro de Preços"}},
    "tudo aprovado": {"documentos": dict.fromkeys(("dfd", "etp", "tr", "edital"), TEXTO),
                      "aprovados": ["dfd", "etp", "tr", "edital"]},
    "srp tudo aprovado": {"dados": {"modelo_execucao": "Registro de Preços"},
                          "documentos": dict.fromkeys(("dfd", "etp", "tr", "edital", "arp"), TEXTO),
                          "aprovados": ["dfd", "etp", "tr", "edital"]},
}


@pytest.mark.parametrize("caso", CASOS)
def test_linha_leve_da_a_mesma_resposta_que_a_inteira(caso):
    linha = _inteira(**CASOS[caso])
    assert _para_contrato(_como_o_postgrest_devolve(linha)) == _para_contrato(linha)


def test_os_casos_cobrem_todos_os_status():
    vistos = {_para_contrato(_inteira(**c)).status for c in CASOS.values()}
    assert vistos == {"Em elaboração", "Aguardando pesquisa de preços", "Em revisão", "Concluído"}


def test_o_recorte_nao_traz_o_texto_dos_documentos():
    colunas = _COLUNAS_DO_RESUMO.split(",")
    assert "documentos" not in colunas
    assert "dados" not in colunas
    assert "documentos_gerados" in colunas
