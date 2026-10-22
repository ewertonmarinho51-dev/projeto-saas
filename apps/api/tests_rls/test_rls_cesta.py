"""
Cesta de preços pela API, contra Postgres + GoTrue + PostgREST reais.

Aqui roda o serviço VERDADEIRO do domínio (`cotacoes.alterar_status_
referencia`), com o token do usuário chegando ao `db.py` pela sessão da
requisição — sem Streamlit no processo. O que se prova é a ponta inteira:
recalcula e grava, a trilha registra, a revisão anda, a revisão velha é
recusada, e quem não pode escrever (outro município, colega que não é o
dono) não muda nada no banco.
"""

from __future__ import annotations

import pytest


@pytest.fixture
def pesquisa(pilha):
    import pilha as modulo_pilha

    return modulo_pilha.semear_precos(pilha)       # uma nova a cada prova


@pytest.fixture(scope="module")
def api_precos(pilha):
    from fastapi.testclient import TestClient

    from govconect_api.config import carregar
    from govconect_api.main import criar_app

    config = carregar({"APP_ENV": "test", "SUPABASE_URL": pilha.url,
                       "SUPABASE_KEY": pilha.anon, "PRICE_RESEARCH_ENABLED": "1",
                       "GOVCONECT_LIMITE_POR_MINUTO": "10000"})
    return TestClient(criar_app(config), raise_server_exceptions=False)


def _url(p, ref):
    return f"/api/v1/precos/pesquisas/{p['pesquisa']}/itens/{p['item']}/referencias/{ref}"


def _referencia(pilha, item):
    import psycopg

    with psycopg.connect(pilha.dsn) as c:
        return c.execute("select id::text, status from public.pesquisa_preco_referencias "
                         "where item_id = %s", (item,)).fetchone()


def _revisao(pilha, item):
    import psycopg

    with psycopg.connect(pilha.dsn) as c:
        return c.execute("select revisao from public.pesquisa_preco_itens where id = %s",
                         (item,)).fetchone()[0]


def _h(conta, revisao):
    return {"Authorization": f"Bearer {conta.token}", "If-Match": f'"{revisao}"'}


def test_dono_tira_da_cesta_recalcula_e_registra(api_precos, pilha, pesquisa):
    import psycopg

    ref, status = _referencia(pilha, pesquisa["item"])
    assert status == "selected"
    antes = _revisao(pilha, pesquisa["item"])
    r = api_precos.patch(_url(pesquisa, ref), headers=_h(pilha.contas["a1"], antes),
                         json={"incluir": False})
    assert r.status_code == 200, r.text
    corpo = r.json()
    assert corpo["revisao"] > antes
    assert _referencia(pilha, pesquisa["item"])[1] == "rejected"
    with psycopg.connect(pilha.dsn) as c:
        evento = c.execute(
            "select tipo, ator::text from public.pesquisa_preco_eventos "
            "where pesquisa_id = %s and tipo = 'referencia_excluida'",
            (pesquisa["pesquisa"],)).fetchone()
    assert evento == ("referencia_excluida", pilha.contas["a1"].auth_user_id)


def test_revisao_velha_e_409_e_nada_muda(api_precos, pilha, pesquisa):
    ref, _ = _referencia(pilha, pesquisa["item"])
    antes = _revisao(pilha, pesquisa["item"])
    r = api_precos.patch(_url(pesquisa, ref), headers=_h(pilha.contas["a1"], antes + 7),
                         json={"incluir": False})
    assert r.status_code == 409
    assert _referencia(pilha, pesquisa["item"])[1] == "selected"


def test_incluir_sem_motivo_e_recusado_pela_regra(api_precos, pilha, pesquisa):
    ref, _ = _referencia(pilha, pesquisa["item"])
    a1 = pilha.contas["a1"]
    revisao = _revisao(pilha, pesquisa["item"])
    tirou = api_precos.patch(_url(pesquisa, ref), headers=_h(a1, revisao), json={"incluir": False})
    assert tirou.status_code == 200, tirou.text
    r = api_precos.patch(_url(pesquisa, ref), headers=_h(a1, tirou.json()["revisao"]),
                         json={"incluir": True})
    assert r.status_code == 422
    assert "motivo" in r.json()["message"]
    assert _referencia(pilha, pesquisa["item"])[1] == "rejected"


@pytest.mark.parametrize("rotulo", ["b1", "a2", "a1_colega"])
def test_quem_nao_pode_escrever_nao_muda_o_banco(api_precos, pilha, pesquisa, rotulo):
    ref, _ = _referencia(pilha, pesquisa["item"])
    revisao = _revisao(pilha, pesquisa["item"])
    r = api_precos.patch(_url(pesquisa, ref), headers=_h(pilha.contas[rotulo], revisao),
                         json={"incluir": False})
    # Recusa de AUTORIZAÇÃO ou de regra — nunca 401: a sessão é válida, e
    # um 401 aqui foi exatamente o que fez esta prova passar pelo motivo
    # errado na primeira versão (o domínio sem configuração recusava tudo).
    assert r.status_code in (403, 404, 409, 422), (rotulo, r.status_code, r.text)
    assert _referencia(pilha, pesquisa["item"])[1] == "selected"
    assert _revisao(pilha, pesquisa["item"]) == revisao
