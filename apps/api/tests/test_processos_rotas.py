"""
Rotas de processos contra um PostgREST SIMULADO.

O que se prova aqui é o que a API MANDA ao banco e o que ela devolve ao
cliente: o token do usuário em toda chamada, identidade nunca vinda do
corpo, If-Match obrigatório, cursor, idempotência, limite. O que o
banco FAZ com isso (RLS, isolamento A×B, trava otimista de verdade) é
`tests_rls/`, contra Postgres, GoTrue e PostgREST reais.
"""

import pytest
from fastapi.testclient import TestClient

from govconect_api.config import carregar
from govconect_api.main import criar_app
from govconect_api.verificador import VerificadorSupabase

from apoio_jwt import (EMISSOR, SECRETARIA_A, TENANT_A, USUARIO_A, Emissor,
                       LINHA_A, PostgrestFalso)

ID = "cccccccc-0000-4000-8000-000000000001"
VERSAO = "2026-10-22T14:00:00.123456+00:00"


def _linha(**extra):
    base = {"id": ID, "nome": "", "orgao": "Secretaria de Saúde",
            "objeto": "Aquisição de luvas", "etapa": 0, "dados": {"orgao": "Secretaria de Saúde",
                                                                  "objeto": "Aquisição de luvas"},
            "documentos": {}, "aprovados": [], "criado_em": VERSAO,
            "atualizado_em": VERSAO, "secretaria_id": SECRETARIA_A,
            "auth_user_id": USUARIO_A, "idempotency_key": "chave-0001"}
    return {**base, **extra}


@pytest.fixture
def emissor():
    return Emissor()


@pytest.fixture
def banco():
    return PostgrestFalso()


@pytest.fixture
def api(emissor, banco):
    def montar(limite=120):
        config = carregar({"APP_ENV": "test",
                           "SUPABASE_URL": "https://exemplo-staging.supabase.co",
                           "SUPABASE_KEY": "chave-publicavel-de-teste",
                           "GOVCONECT_LIMITE_POR_MINUTO": str(limite)})
        rest = banco.cliente()
        verificador = VerificadorSupabase(emissor=EMISSOR, rest=rest,
                                          chave_para=emissor.chave_para)
        return TestClient(criar_app(config, verificador=verificador, rest=rest),
                          raise_server_exceptions=False)
    return montar


def _auth(emissor, **kw):
    return {"Authorization": f"Bearer {emissor.token(**kw)}"}


def test_me_devolve_identidade_do_token(api, emissor):
    r = api().get("/api/v1/me", headers=_auth(emissor))
    assert r.status_code == 200
    assert r.json() == {"auth_user_id": USUARIO_A, "tenant_id": TENANT_A,
                        "papel": "usuario", "secretaria_id": SECRETARIA_A,
                        "governanca": False}


def test_sem_vinculo_e_403_sem_dizer_por_que(api, emissor, banco):
    banco.usuarios = []
    r = api().get("/api/v1/me", headers=_auth(emissor))
    assert r.status_code == 403
    assert r.json()["message"] == "Acesso negado"


def test_listar_usa_token_do_usuario_e_pagina_por_cursor(api, emissor, banco):
    linhas = [_linha(id=f"cccccccc-0000-4000-8000-00000000000{i}",
                     atualizado_em=f"2026-10-22T14:00:0{i}+00:00") for i in (3, 2, 1)]
    banco.responder("GET", "processos", 200, linhas)
    cliente = api()
    cabecalhos = _auth(emissor)
    r = cliente.get("/api/v1/processos?limit=2", headers=cabecalhos)
    assert r.status_code == 200
    corpo = r.json()
    assert [p["id"][-1] for p in corpo["itens"]] == ["3", "2"]
    assert corpo["proximo_cursor"]
    assert corpo["itens"][0]["status"] and corpo["itens"][0]["progresso"]["total"] >= 1

    chamada = banco.chamadas[-1]
    assert chamada.headers["authorization"] == cabecalhos["Authorization"]
    assert chamada.url.params["tenant_id"] == f"eq.{TENANT_A}"
    assert chamada.url.params["limit"] == "3"

    banco.responder("GET", "processos", 200, [])
    cliente.get(f"/api/v1/processos?limit=2&cursor={corpo['proximo_cursor']}",
                headers=cabecalhos)
    filtro = banco.chamadas[-1].url.params["or"]
    assert '"2026-10-22T14:00:02+00:00"' in filtro and "id.lt.cccccccc" in filtro


def test_cursor_adulterado_e_400(api, emissor):
    r = api().get("/api/v1/processos?cursor=bm9wZQ", headers=_auth(emissor))
    assert r.status_code == 400
    assert r.json()["code"] == "INVALID_CURSOR"


@pytest.mark.parametrize("limit", [0, 101])
def test_limite_de_pagina_fora_da_faixa_e_422(api, emissor, limit):
    assert api().get(f"/api/v1/processos?limit={limit}",
                     headers=_auth(emissor)).status_code == 422


@pytest.mark.parametrize("campo", ["tenant_id", "auth_user_id", "papel",
                                   "secretaria_id", "usuario_id"])
def test_identidade_no_corpo_e_recusada(api, emissor, banco, campo):
    r = api().post("/api/v1/processos",
                   headers={**_auth(emissor), "Idempotency-Key": "chave-0001"},
                   json={"orgao": "x", "objeto": "y",
                         campo: "bbbbbbbb-0000-4000-8000-000000000002"})
    assert r.status_code == 422
    assert not any(c.method == "POST" for c in banco.chamadas)


def test_criar_carimba_identidade_do_token(api, emissor, banco):
    banco.responder("POST", "processos", 201, [_linha()])
    r = api().post("/api/v1/processos",
                   headers={**_auth(emissor), "Idempotency-Key": "chave-0001"},
                   json={"orgao": "Secretaria de Saúde", "objeto": "Aquisição de luvas"})
    assert r.status_code == 201
    assert r.headers["location"] == f"/api/v1/processos/{ID}"
    assert r.headers["etag"] == f'"{VERSAO}"'
    enviado = banco.corpo(banco.chamadas[-1])
    assert (enviado["tenant_id"], enviado["auth_user_id"], enviado["secretaria_id"],
            enviado["usuario_id"], enviado["idempotency_key"]) == \
        (TENANT_A, USUARIO_A, SECRETARIA_A, LINHA_A, "chave-0001")
    assert enviado["dados"] == {"orgao": "Secretaria de Saúde",
                                "objeto": "Aquisição de luvas"}


def test_criar_sem_idempotency_key_e_422(api, emissor):
    r = api().post("/api/v1/processos", headers=_auth(emissor),
                   json={"orgao": "x", "objeto": "y"})
    assert r.status_code == 422


def test_idempotency_key_com_caractere_invalido_e_400(api, emissor):
    r = api().post("/api/v1/processos",
                   headers={**_auth(emissor), "Idempotency-Key": "chave com espaco"},
                   json={"orgao": "x", "objeto": "y"})
    assert r.status_code == 400


def test_repeticao_da_mesma_chave_devolve_o_mesmo_processo(api, emissor, banco):
    banco.responder("POST", "processos", 409, {"code": "23505"})
    banco.responder("GET", "processos", 200, [_linha()])
    r = api().post("/api/v1/processos",
                   headers={**_auth(emissor), "Idempotency-Key": "chave-0001"},
                   json={"orgao": "Secretaria de Saúde", "objeto": "Aquisição de luvas"})
    assert r.status_code == 200
    assert r.headers["idempotent-replayed"] == "true"
    assert r.json()["id"] == ID


def test_mesma_chave_com_outro_conteudo_e_409(api, emissor, banco):
    banco.responder("POST", "processos", 409, {"code": "23505"})
    banco.responder("GET", "processos", 200, [_linha()])
    r = api().post("/api/v1/processos",
                   headers={**_auth(emissor), "Idempotency-Key": "chave-0001"},
                   json={"orgao": "Outro órgão", "objeto": "Aquisição de luvas"})
    assert r.status_code == 409
    assert r.json()["code"] == "IDEMPOTENCY_KEY_REUSED"


def test_mesma_chave_de_outro_usuario_nao_devolve_o_processo_dele(api, emissor, banco):
    banco.responder("POST", "processos", 409, {"code": "23505"})
    banco.responder("GET", "processos", 200, [_linha(
        auth_user_id="dddddddd-0000-4000-8000-000000000009")])
    r = api().post("/api/v1/processos",
                   headers={**_auth(emissor), "Idempotency-Key": "chave-0001"},
                   json={"orgao": "Secretaria de Saúde", "objeto": "Aquisição de luvas"})
    assert r.status_code == 409
    assert ID not in r.text


def test_consultar_inexistente_ou_alheio_e_404(api, emissor, banco):
    banco.responder("GET", "processos", 200, [])
    r = api().get(f"/api/v1/processos/{ID}", headers=_auth(emissor))
    assert r.status_code == 404


def test_patch_sem_if_match_e_428(api, emissor):
    r = api().patch(f"/api/v1/processos/{ID}", headers=_auth(emissor),
                    json={"objeto": "novo"})
    assert r.status_code == 428


def test_patch_com_versao_velha_e_409_sem_escrever(api, emissor, banco):
    banco.responder("GET", "processos", 200, [_linha()])
    r = api().patch(f"/api/v1/processos/{ID}",
                    headers={**_auth(emissor), "If-Match": '"2026-01-01T00:00:00+00:00"'},
                    json={"objeto": "novo"})
    assert r.status_code == 409
    assert not any(c.method == "PATCH" for c in banco.chamadas)


def test_patch_filtra_pela_versao_e_espelha_em_dados(api, emissor, banco):
    banco.responder("GET", "processos", 200, [_linha()])
    banco.responder("PATCH", "processos", 200, [_linha(
        objeto="novo", atualizado_em="2026-10-22T14:00:09+00:00")])
    r = api().patch(f"/api/v1/processos/{ID}",
                    headers={**_auth(emissor), "If-Match": f'"{VERSAO}"'},
                    json={"objeto": "novo"})
    assert r.status_code == 200
    assert r.headers["etag"] == '"2026-10-22T14:00:09+00:00"'
    patch = next(c for c in banco.chamadas if c.method == "PATCH")
    assert patch.url.params["atualizado_em"] == f"eq.{VERSAO}"
    assert banco.corpo(patch)["dados"]["objeto"] == "novo"


def test_patch_que_perde_a_corrida_e_409(api, emissor, banco):
    # A leitura viu a versão certa, mas outro PATCH chegou antes ao banco:
    # o filtro de versão casa zero linhas.
    banco.responder("GET", "processos", 200, [_linha()])
    banco.responder("PATCH", "processos", 200, [])
    banco.responder("GET", "processos", 200, [_linha(atualizado_em="2026-10-22T14:00:09+00:00")])
    r = api().patch(f"/api/v1/processos/{ID}",
                    headers={**_auth(emissor), "If-Match": f'"{VERSAO}"'},
                    json={"objeto": "novo"})
    assert r.status_code == 409


def test_patch_de_colega_que_nao_e_dono_e_403(api, emissor, banco):
    banco.responder("GET", "processos", 200, [_linha(
        auth_user_id="dddddddd-0000-4000-8000-000000000009")])
    r = api().patch(f"/api/v1/processos/{ID}",
                    headers={**_auth(emissor), "If-Match": f'"{VERSAO}"'},
                    json={"objeto": "novo"})
    assert r.status_code == 403


def test_patch_nao_aceita_trocar_o_municipio(api, emissor):
    r = api().patch(f"/api/v1/processos/{ID}",
                    headers={**_auth(emissor), "If-Match": f'"{VERSAO}"'},
                    json={"tenant_id": "bbbbbbbb-0000-4000-8000-000000000002"})
    assert r.status_code == 422


def test_banco_fora_do_ar_e_503_sem_detalhe(api, emissor, banco):
    import httpx

    def cair(request):
        raise httpx.ConnectError("https://exemplo-staging.supabase.co recusou")

    cliente = api()
    cliente.app.state.rest._http._transport = httpx.MockTransport(cair)
    r = cliente.get("/api/v1/me", headers=_auth(emissor))
    assert r.status_code == 503
    assert "supabase" not in r.text


def test_limite_por_usuario_devolve_429_com_retry_after(api, emissor):
    cliente = api(limite=2)
    cabecalhos = _auth(emissor)
    assert [cliente.get("/api/v1/me", headers=cabecalhos).status_code
            for _ in range(3)] == [200, 200, 429]
    r = cliente.get("/api/v1/me", headers=cabecalhos)
    assert int(r.headers["retry-after"]) >= 1
    # Outro usuário tem a própria cota.
    outro = _auth(emissor, sub="eeeeeeee-0000-4000-8000-000000000005")
    assert cliente.get("/api/v1/me", headers=outro).status_code == 200
