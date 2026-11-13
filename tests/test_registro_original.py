"""
"Consultar registro original" (13/11/2026): o item exato e o resultado da
fonte oficial que deram origem ao preço, legíveis, com o link de origem e o
dado oficial exato. Sem rede.
"""

from __future__ import annotations

from src.precos import links

CAREACU = "17935388000115-1-000108/2026"


def _linha_pncp(**extra):
    return {
        "fonte_id": "pncp", "fonte_nome": "PNCP — Portal Nacional de Contratações Públicas",
        "descricao_original": "ANALISADOR BIOQUÍMICO SEMIAUTOMÁTICO",
        "unidade_original": "UN", "valor_unitario_original": "12300.000000",
        "fornecedor": "Fornecedor Ltda", "data_resultado": "2026-10-29",
        "bruto": {
            "numeroControlePNCP": CAREACU,
            "item": {"numeroItem": 2, "descricao": "ANALISADOR BIOQUÍMICO SEMIAUTOMÁTICO",
                     "unidadeMedida": "UN", "criterioJulgamentoNome": "Menor preço"},
            "resultado": {"valorUnitarioHomologado": 12300.0, "quantidadeHomologada": 1.0,
                          "valorTotalHomologado": 12300.0,
                          "nomeRazaoSocialFornecedor": "Fornecedor Ltda",
                          "dataResultado": "2026-10-29T00:00:00"},
        },
        **extra,
    }


def test_registro_do_pncp_aponta_o_item_exato_e_o_resultado():
    registro = links.registro_original(_linha_pncp())
    assert registro["numero_controle"] == CAREACU
    assert registro["numero_item"] == 2
    assert registro["descricao"] == "ANALISADOR BIOQUÍMICO SEMIAUTOMÁTICO"
    assert registro["valor_unitario"] == 12300.0
    assert registro["data_resultado"] == "2026-10-29"
    # a página de origem (o PNCP não tem página por item) e o dado oficial exato
    assert registro["pagina_url"] == "https://pncp.gov.br/app/editais/17935388000115/2026/108"
    assert registro["dados_url"] == ("https://pncp.gov.br/api/pncp/v1/orgaos/"
                                     "17935388000115/compras/2026/108/itens/2/resultados")


def test_sem_numero_do_item_fica_so_a_pagina_de_origem():
    linha = _linha_pncp()
    del linha["bruto"]["item"]["numeroItem"]
    registro = links.registro_original(linha)
    assert registro["numero_item"] is None and registro["dados_url"] is None
    assert registro["pagina_url"].startswith("https://pncp.gov.br/app/editais/")


def test_sem_link_oficial_nao_ha_registro():
    assert links.registro_original({"fonte_id": "outra", "bruto": {}}) is None


def test_api_entrega_o_registro_com_valor_exato():
    import sys
    from pathlib import Path

    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "apps" / "api"))
    try:
        from govconect_api import precos as rotas
    except ImportError:          # a suíte da raiz roda sem a API instalada
        import pytest

        pytest.skip("pacote da API indisponível neste ambiente")
    registro = rotas._registro_original(_linha_pncp())
    assert registro.valor_unitario.exibicao == "R$ 12.300,00"
    assert registro.valor_unitario.valor == "12300.0"
    assert registro.numero_item == 2
