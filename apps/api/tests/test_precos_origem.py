"""
A referência sai da API com ORIGEM e CANAL separados (cotação automática
multiportal, 10/11/2026): "Origem Licitanet · Coleta via PNCP".

A atribuição é a do domínio (`src.precos.portais`), sobre o `bruto` que a
coleta gravou; o `bruto` em si não sai da API.
"""

from govconect_api import precos as api_precos

LINHA = {
    "id": "r1", "fonte_id": "pncp", "fonte_nome": "PNCP",
    "fonte_tipo": "contratacao_similar", "natureza_valor": "homologado",
    "status": "candidate", "descricao_original": "GASOLINA COMUM",
    "unidade_original": "Litro", "coletado_em": "2026-11-10T10:00:00+00:00",
    "motivos": [],
    "bruto": {"numeroControlePNCP": "04873600000115-1-000173/2026",
              "usuarioNome": "LICITANET LICITACOES ELETRONICAS LTDA",
              "linkSistemaOrigem": "https://licitanet.com.br/sessao/123"},
}


def test_pncp_com_origem_corroborada():
    saida = api_precos._referencia(LINHA)
    assert saida.origem == "Licitanet"
    assert saida.canal == "Coleta via PNCP"
    assert saida.rotulo_origem == "Origem Licitanet · Coleta via PNCP"
    assert saida.link_contratacao == (
        "https://pncp.gov.br/app/editais/04873600000115/2026/173")


def test_pncp_com_evidencia_contraditoria_nao_inventa_origem():
    linha = {**LINHA, "bruto": {**LINHA["bruto"],
                                "linkSistemaOrigem": "https://bnccompras.com/x"}}
    saida = api_precos._referencia(linha)
    assert saida.origem == "Origem não identificada"
    assert saida.rotulo_origem == "Origem não identificada · Coleta via PNCP"


def test_fonte_sem_origem_declarada_fica_vazia():
    saida = api_precos._referencia({**LINHA, "fonte_id": "outra", "bruto": {}})
    assert (saida.origem, saida.canal, saida.rotulo_origem) == ("", "", "")
    compras = api_precos._referencia({**LINHA, "fonte_id": "compras_gov_precos",
                                      "bruto": {}})
    assert compras.origem == "Compras.gov.br"
    assert compras.canal == "Coleta via Compras.gov.br (dados abertos)"


def test_rotulo_de_equivalencia_vem_do_fator_gravado():
    fatores = [{"nome": "descricao", "explicacao": "x"},
               {"nome": "equivalencia", "explicacao":
                "equivalente comprovado — conferido: formato A4; gramatura 75 g/m²"}]
    saida = api_precos._referencia({**LINHA, "fatores": fatores})
    assert saida.equivalencia == "equivalente comprovado"
    assert "gramatura 75 g/m²" in saida.equivalencia_detalhe
    # texto que não é rótulo conhecido não vira rótulo
    estranho = [{"nome": "equivalencia", "explicacao": "<script>"}]
    assert api_precos._referencia({**LINHA, "fatores": estranho}).equivalencia == ""
    assert api_precos._referencia(LINHA).equivalencia == ""
