"""
Leitura de pesquisas de preços contra Postgres + GoTrue + PostgREST reais.

O predicado da 0021 (`pode_ler_pesquisa_preco`): mesmo tenant e (admin,
dono, ou mesma secretaria). Cada conta da pilha testa um ramo dele. E o
dinheiro: um `numeric(18,4)` que não cabe em float tem de atravessar
banco → PostgREST → API sem perder dígito.
"""

from __future__ import annotations

import pytest


@pytest.fixture(scope="module")
def dados(pilha):
    import pilha as modulo_pilha

    return modulo_pilha.semear_precos(pilha)


@pytest.fixture(scope="module")
def api_precos(pilha):
    from fastapi.testclient import TestClient

    from govconect_api.config import carregar
    from govconect_api.main import criar_app

    config = carregar({"APP_ENV": "test", "SUPABASE_URL": pilha.url,
                       "SUPABASE_KEY": pilha.anon, "PRICE_RESEARCH_ENABLED": "1",
                       "GOVCONECT_LIMITE_POR_MINUTO": "10000"})
    return TestClient(criar_app(config), raise_server_exceptions=False)


def _h(conta):
    return {"Authorization": f"Bearer {conta.token}"}


def test_dono_le_com_dinheiro_exato(api_precos, pilha, dados):
    r = api_precos.get(f"/api/v1/precos/pesquisas/{dados['pesquisa']}", headers=_h(pilha.contas["a1"]))
    assert r.status_code == 200, r.text
    corpo = r.json()
    assert corpo["valor_global"]["valor"] == "12345678901234.5678"
    assert [i["numero"] for i in corpo["itens"]] == [1]      # o retirado não vem
    item = corpo["itens"][0]
    assert item["preco_estimado"] == {"valor": "2.3450", "exibicao": "R$ 2,35"}
    assert item["quantidade"]["exibicao"] == "1.500"


@pytest.mark.parametrize("rotulo, esperado", [
    ("a1_colega", 200),   # mesma secretaria
    ("admin_a", 200),     # admin do município
    ("a2", 404),          # outra secretaria do mesmo município
    ("b1", 404),          # outro município
])
def test_ramos_do_predicado_de_leitura(api_precos, pilha, dados, rotulo, esperado):
    r = api_precos.get(f"/api/v1/precos/pesquisas/{dados['pesquisa']}",
                       headers=_h(pilha.contas[rotulo]))
    assert r.status_code == esperado


def test_lista_de_outro_municipio_nao_traz_a_pesquisa(api_precos, pilha, dados):
    r = api_precos.get("/api/v1/precos/pesquisas?limit=100", headers=_h(pilha.contas["b1"]))
    assert r.status_code == 200
    assert dados["pesquisa"] not in [p["id"] for p in r.json()["itens"]]


def test_rls_esconde_mesmo_sem_filtro_da_api(pilha, dados):
    import httpx

    for tabela, coluna, valor in (("pesquisas_preco", "id", dados["pesquisa"]),
                                  ("pesquisa_preco_itens", "id", dados["item"]),
                                  ("pesquisa_preco_referencias", "item_id", dados["item"])):
        r = httpx.get(f"{pilha.url}/rest/v1/{tabela}",
                      params={"select": "id", coluna: f"eq.{valor}"},
                      headers={"apikey": pilha.anon,
                               "Authorization": f"Bearer {pilha.contas['b1'].token}"})
        assert r.status_code == 200 and r.json() == [], tabela


def test_referencias_com_link_oficial(api_precos, pilha, dados):
    r = api_precos.get(f"/api/v1/precos/pesquisas/{dados['pesquisa']}/itens/{dados['item']}/referencias",
                       headers=_h(pilha.contas["a1"]))
    assert r.status_code == 200, r.text
    (ref,) = r.json()
    assert ref["link_contratacao"] == "https://pncp.gov.br/app/editais/12345678000190/2025/123"
    assert ref["valor_unitario_normalizado"]["valor"] == "2.3456"


def test_item_por_url_de_outra_pesquisa_e_404(api_precos, pilha, dados):
    r = api_precos.get(f"/api/v1/precos/pesquisas/{dados['vazia']}/itens/{dados['item']}/referencias",
                       headers=_h(pilha.contas["a1"]))
    assert r.status_code == 404


def test_referencias_de_outro_municipio_sao_404(api_precos, pilha, dados):
    r = api_precos.get(f"/api/v1/precos/pesquisas/{dados['pesquisa']}/itens/{dados['item']}/referencias",
                       headers=_h(pilha.contas["b1"]))
    assert r.status_code == 404
