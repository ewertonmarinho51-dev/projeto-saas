"""
Autorização da API provada contra Postgres + GoTrue + PostgREST reais.

05_SEGURANCA, testes de ataque mínimos 1–5, no que cabe a processos:
sem credencial, token forjado, troca de município por id, promoção pelo
corpo, usuário revogado, edição concorrente e repetição de criação.
Cada token de usuário veio de login por senha no GoTrue oficial.
"""

from __future__ import annotations

import time
import uuid
from concurrent.futures import ThreadPoolExecutor

import jwt
import pytest


def _h(conta, **extra):
    return {"Authorization": f"Bearer {conta.token}", **extra}


def _criar(api, conta, objeto=None, chave=None):
    r = api.post("/api/v1/processos",
                 headers=_h(conta, **{"Idempotency-Key": chave or f"k-{uuid.uuid4().hex}"}),
                 json={"orgao": "Secretaria de Saúde",
                       "objeto": objeto or f"Aquisição {uuid.uuid4().hex[:6]}"})
    assert r.status_code == 201, r.text
    return r


@pytest.fixture(scope="module")
def processo_a1(api, pilha):
    return _criar(api, pilha.contas["a1"]).json()


# -- identidade ------------------------------------------------------------
def test_me_devolve_o_vinculo_do_token_real(api, pilha):
    a1 = pilha.contas["a1"]
    r = api.get("/api/v1/me", headers=_h(a1))
    assert r.status_code == 200, r.text
    assert r.json() == {"auth_user_id": a1.auth_user_id, "tenant_id": a1.tenant_id,
                        "papel": "usuario", "secretaria_id": a1.secretaria_id,
                        # servidor comum, sem papel de governança: sem Centro
                        "governanca": False}


def test_sem_credencial_e_401(api):
    assert api.get("/api/v1/processos").status_code == 401


def test_token_forjado_com_outra_chave_e_401(api, pilha):
    from cryptography.hazmat.primitives.asymmetric import ec

    a1 = pilha.contas["a1"]
    verdadeiro = jwt.decode(a1.token, options={"verify_signature": False})
    kid = jwt.get_unverified_header(a1.token)["kid"]
    forjado = jwt.encode({**verdadeiro, "app_metadata": {
        **verdadeiro["app_metadata"], "papel": "admin"}},
        ec.generate_private_key(ec.SECP256R1()), algorithm="ES256",
        headers={"kid": kid})
    assert api.get("/api/v1/me", headers={"Authorization": f"Bearer {forjado}"}).status_code == 401


def test_token_hs256_valido_para_o_postgrest_e_recusado_pela_api(api, pilha):
    # Quem tiver o segredo HS256 legado consegue um token que o PostgREST
    # aceita. A API verifica só ES256 pelo JWKS: o legado não entra por ela.
    a1 = pilha.contas["a1"]
    claims = jwt.decode(a1.token, options={"verify_signature": False})
    hs = jwt.encode(claims, pilha.segredo_hs256, algorithm="HS256")
    assert api.get("/api/v1/me", headers={"Authorization": f"Bearer {hs}"}).status_code == 401


def test_usuario_revogado_perde_acesso_com_token_ainda_valido(api, pilha):
    r = api.get("/api/v1/me", headers=_h(pilha.contas["a1_revogado"]))
    assert r.status_code == 403


def test_revogar_no_meio_da_sessao_corta_na_requisicao_seguinte(api, pilha):
    import psycopg

    colega = pilha.contas["a1_colega"]
    assert api.get("/api/v1/me", headers=_h(colega)).status_code == 200
    with psycopg.connect(pilha.dsn, autocommit=True) as c:
        c.execute("update public.usuarios set ativo=false where auth_user_id=%s",
                  (colega.auth_user_id,))
    try:
        assert api.get("/api/v1/me", headers=_h(colega)).status_code == 403
    finally:
        with psycopg.connect(pilha.dsn, autocommit=True) as c:
            c.execute("update public.usuarios set ativo=true where auth_user_id=%s",
                      (colega.auth_user_id,))


# -- isolamento ------------------------------------------------------------
def test_criar_carimba_tenant_e_dono_do_token(api, pilha, processo_a1):
    import psycopg

    a1 = pilha.contas["a1"]
    with psycopg.connect(pilha.dsn) as c:
        linha = c.execute("select tenant_id, auth_user_id, secretaria_id from public.processos "
                          "where id=%s", (processo_a1["id"],)).fetchone()
    assert tuple(map(str, linha)) == (a1.tenant_id, a1.auth_user_id, a1.secretaria_id)


def test_outro_municipio_nao_ve_nem_toca(api, pilha, processo_a1):
    b1 = pilha.contas["b1"]
    pid = processo_a1["id"]
    assert pid not in [p["id"] for p in api.get("/api/v1/processos?limit=100",
                                                 headers=_h(b1)).json()["itens"]]
    assert api.get(f"/api/v1/processos/{pid}", headers=_h(b1)).status_code == 404
    r = api.patch(f"/api/v1/processos/{pid}",
                  headers=_h(b1, **{"If-Match": f'"{processo_a1["versao"]}"'}),
                  json={"objeto": "sequestro"})
    assert r.status_code == 404


def test_o_rls_e_a_barreira_e_nao_o_filtro_da_api(pilha, processo_a1):
    # Direto no PostgREST, com o token de B e SEM filtro de tenant: o
    # banco sozinho tem de esconder o processo de A.
    import httpx

    r = httpx.get(f"{pilha.url}/rest/v1/processos",
                  params={"select": "id", "id": f"eq.{processo_a1['id']}"},
                  headers={"apikey": pilha.anon,
                           "Authorization": f"Bearer {pilha.contas['b1'].token}"})
    assert r.status_code == 200 and r.json() == []


def test_outra_secretaria_do_mesmo_municipio_nao_ve(api, pilha, processo_a1):
    assert api.get(f"/api/v1/processos/{processo_a1['id']}",
                   headers=_h(pilha.contas["a2"])).status_code == 404


def test_colega_ve_mas_nao_edita(api, pilha, processo_a1):
    colega = pilha.contas["a1_colega"]
    r = api.get(f"/api/v1/processos/{processo_a1['id']}", headers=_h(colega))
    assert r.status_code == 200
    r = api.patch(f"/api/v1/processos/{processo_a1['id']}",
                  headers=_h(colega, **{"If-Match": r.headers["etag"]}),
                  json={"objeto": "edição do colega"})
    assert r.status_code == 403


def test_admin_do_municipio_edita(api, pilha):
    pid = _criar(api, pilha.contas["a1"]).json()["id"]
    admin = pilha.contas["admin_a"]
    atual = api.get(f"/api/v1/processos/{pid}", headers=_h(admin))
    r = api.patch(f"/api/v1/processos/{pid}",
                  headers=_h(admin, **{"If-Match": atual.headers["etag"]}),
                  json={"objeto": "revisado pelo admin"})
    assert r.status_code == 200, r.text
    assert r.json()["objeto"] == "revisado pelo admin"


def test_promocao_pelo_corpo_e_recusada(api, pilha):
    r = api.post("/api/v1/processos",
                 headers=_h(pilha.contas["a1"], **{"Idempotency-Key": f"k-{uuid.uuid4().hex}"}),
                 json={"orgao": "x", "objeto": "y",
                       "tenant_id": pilha.contas["b1"].tenant_id})
    assert r.status_code == 422


def test_paginacao_por_cursor_nao_repete_nem_pula(api, pilha):
    conta = pilha.contas["a2"]
    criados = {_criar(api, conta).json()["id"] for _ in range(5)}
    vistos, cursor = [], None
    for _ in range(10):
        url = "/api/v1/processos?limit=2" + (f"&cursor={cursor}" if cursor else "")
        corpo = api.get(url, headers=_h(conta)).json()
        vistos += [p["id"] for p in corpo["itens"]]
        cursor = corpo["proximo_cursor"]
        if not cursor:
            break
    assert len(vistos) == len(set(vistos))
    assert criados <= set(vistos)


# -- concorrência ----------------------------------------------------------
def test_dois_patch_com_a_mesma_versao_um_vence_outro_409(api, pilha):
    a1 = pilha.contas["a1"]
    criado = _criar(api, a1)
    pid, etag = criado.json()["id"], criado.headers["etag"]

    def editar(texto):
        return api.patch(f"/api/v1/processos/{pid}",
                         headers=_h(a1, **{"If-Match": etag}), json={"objeto": texto}).status_code

    with ThreadPoolExecutor(2) as ex:
        codigos = sorted(ex.map(editar, ["primeira", "segunda"]))
    assert codigos == [200, 409]


def test_mesma_idempotency_key_nao_duplica_nem_em_paralelo(api, pilha):
    import psycopg

    a1 = pilha.contas["a1"]
    chave = f"k-{uuid.uuid4().hex}"
    corpo = {"orgao": "Secretaria de Saúde", "objeto": "Compra única"}

    def criar(_):
        r = api.post("/api/v1/processos", headers=_h(a1, **{"Idempotency-Key": chave}),
                     json=corpo)
        return r.status_code, r.json().get("id")

    with ThreadPoolExecutor(4) as ex:
        resultados = list(ex.map(criar, range(4)))
    assert {c for c, _ in resultados} <= {200, 201}
    assert sum(c == 201 for c, _ in resultados) == 1
    assert len({i for _, i in resultados}) == 1
    with psycopg.connect(pilha.dsn) as c:
        total = c.execute("select count(*) from public.processos where idempotency_key=%s",
                          (chave,)).fetchone()[0]
    assert total == 1


# -- busca -----------------------------------------------------------------
def test_busca_acha_pelo_banco_e_nao_atravessa_municipio(api, pilha):
    """`q` filtra no PostgREST sobre a base inteira, com o RLS valendo."""
    a1, b1 = pilha.contas["a1"], pilha.contas["b1"]
    marca = uuid.uuid4().hex[:8]
    alvo = _criar(api, a1, objeto=f"Aquisição de lâmpadas LED {marca}").json()
    _criar(api, a1, objeto=f"Serviço de limpeza {uuid.uuid4().hex[:8]}")
    # Mais de uma página de processos depois do alvo: a busca não pode
    # depender de o alvo estar na primeira página.
    for _ in range(3):
        _criar(api, a1)

    r = api.get(f"/api/v1/processos?limit=1&q=lâmpadas {marca}", headers=_h(a1))
    assert r.status_code == 200, r.text
    assert [p["id"] for p in r.json()["itens"]] == [alvo["id"]]
    assert r.json()["proximo_cursor"] is None

    # Maiúsculas não importam; palavra que não está em campo nenhum zera.
    assert [p["id"] for p in api.get(f"/api/v1/processos?q=LED {marca.upper()}",
                                     headers=_h(a1)).json()["itens"]] == [alvo["id"]]
    assert api.get(f"/api/v1/processos?q={marca} inexistente",
                   headers=_h(a1)).json()["itens"] == []

    # Outro município, mesma busca: nada.
    assert api.get(f"/api/v1/processos?q={marca}", headers=_h(b1)).json()["itens"] == []

    # Sintaxe do PostgREST e curinga do LIKE na busca viram espaço.
    r = api.get("/api/v1/processos", params={"q": '%),or(id.not.is.null'}, headers=_h(a1))
    assert r.status_code == 200
