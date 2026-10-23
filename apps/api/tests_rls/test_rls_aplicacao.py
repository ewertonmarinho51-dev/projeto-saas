"""
Aplicar a pesquisa ao processo contra a pilha real (P04f).

Domínio, banco e RLS verdadeiros. A planilha do processo recebe o preço
da pesquisa, os documentos gerados caem (com a aprovação), a pesquisa vira
APLICADA e a trilha guarda o ato com o ator verdadeiro. A versão vista do
processo protege contra escrita concorrente; colega não aplica.
"""

from __future__ import annotations

import pytest


def _api(pilha):
    from fastapi.testclient import TestClient

    from govconect_api.config import carregar
    from govconect_api.main import criar_app

    config = carregar({"APP_ENV": "test", "SUPABASE_URL": pilha.url, "SUPABASE_KEY": pilha.anon,
                       "PRICE_RESEARCH_ENABLED": "1", "GOVCONECT_LIMITE_POR_MINUTO": "10000"})
    return TestClient(criar_app(config), raise_server_exceptions=False)


def _h(conta, **extra):
    return {"Authorization": f"Bearer {conta.token}", **extra}


@pytest.fixture
def cenario(pilha):
    import pilha as modulo_pilha

    return modulo_pilha.semear_aplicacao(pilha)


def test_aplicar_ao_processo_de_ponta_a_ponta(pilha, cenario):
    import psycopg

    api, a1 = _api(pilha), pilha.contas["a1"]
    url = f"/api/v1/precos/pesquisas/{cenario['pesquisa']}/aplicacao"
    previa = api.get(url, headers=_h(a1))
    assert previa.status_code == 200, previa.text
    corpo = previa.json()
    assert corpo["impedimento"] == "", corpo
    assert corpo["valor_novo"]["exibicao"] == "R$ 351,75"
    assert [d["chave"] for d in corpo["documentos_a_descartar"]] == ["dfd", "etp"]

    sem = api.post(url, headers=_h(a1, **{"If-Match": f'"{corpo["versao_processo"]}"'}), json={})
    assert sem.status_code == 422

    feito = api.post(url, headers=_h(a1, **{"If-Match": f'"{corpo["versao_processo"]}"'}),
                     json={"confirmo_descarte": True})
    assert feito.status_code == 200, feito.text
    assert feito.json()["pesquisa_marcada"] is True

    with psycopg.connect(pilha.dsn) as c:
        dados, documentos, aprovados = c.execute(
            "select dados, documentos, aprovados from public.processos where id=%s",
            (cenario["processo"],)).fetchone()
        estado = c.execute("select estado from public.pesquisas_preco where id=%s",
                           (cenario["pesquisa"],)).fetchone()[0]
        atores = c.execute("select ator::text from public.pesquisa_preco_eventos where pesquisa_id=%s "
                           "and tipo='pesquisa_aplicada'", (cenario["pesquisa"],)).fetchall()
    assert dados["itens"][0]["valor_unitario"] == 2.345
    assert round(dados["valor_estimado"], 2) == 351.75
    assert dados["pesquisa_preco"]["id"] == cenario["pesquisa"]
    assert documentos == {} and aprovados == []
    assert estado == "applied"
    assert atores == [(a1.auth_user_id,)]

    de_novo = api.post(url, headers=_h(a1, **{"If-Match": '"qualquer"'}),
                       json={"confirmo_descarte": True})
    assert de_novo.status_code == 409 and "já foi aplicada" in de_novo.json()["message"]


def test_processo_alterado_depois_da_previa_e_409(pilha, cenario):
    import psycopg

    api, a1 = _api(pilha), pilha.contas["a1"]
    url = f"/api/v1/precos/pesquisas/{cenario['pesquisa']}/aplicacao"
    versao = api.get(url, headers=_h(a1)).json()["versao_processo"]
    with psycopg.connect(pilha.dsn, autocommit=True) as c:   # o Streamlit salvou no meio
        c.execute("update public.processos set objeto='Canetas e lápis' where id=%s",
                  (cenario["processo"],))
    r = api.post(url, headers=_h(a1, **{"If-Match": f'"{versao}"'}), json={"confirmo_descarte": True})
    assert r.status_code == 409 and r.json()["code"] == "VERSION_CONFLICT"
    with psycopg.connect(pilha.dsn) as c:
        assert c.execute("select estado from public.pesquisas_preco where id=%s",
                         (cenario["pesquisa"],)).fetchone() == ("completed",)


def test_colega_ve_a_previa_mas_nao_aplica(pilha, cenario):
    api, colega = _api(pilha), pilha.contas["a1_colega"]
    url = f"/api/v1/precos/pesquisas/{cenario['pesquisa']}/aplicacao"
    previa = api.get(url, headers=_h(colega))
    assert previa.status_code == 200
    r = api.post(url, headers=_h(colega, **{"If-Match": f'"{previa.json()["versao_processo"]}"'}),
                 json={"confirmo_descarte": True})
    assert r.status_code == 403


def test_outro_municipio_nem_ve(pilha, cenario):
    r = _api(pilha).get(f"/api/v1/precos/pesquisas/{cenario['pesquisa']}/aplicacao",
                        headers=_h(pilha.contas["b1"]))
    assert r.status_code == 404
