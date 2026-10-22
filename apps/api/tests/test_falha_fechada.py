"""
A API não autoriza ninguém enquanto não souber verificar.

Os casos são os do gate F1 (05_SEGURANCA, "testes de ataque mínimos",
item 1) que já fazem sentido sem verificador: sem bearer, bearer torto,
esquema errado, e bearer bem formado sem verificador configurado.
Nenhum deles pode terminar em 200.
"""

import pytest

from govconect_api.config import carregar
from govconect_api.main import criar_app
from govconect_api.seguranca import TokenRecusado

from fastapi.testclient import TestClient


def _sem_vazamento(corpo: dict) -> None:
    assert set(corpo) == {"code", "message", "request_id"}
    assert corpo["request_id"]


def test_sem_cabecalho_e_401_com_desafio(cliente):
    r = cliente.get("/api/v1/me")
    assert r.status_code == 401
    assert r.headers["www-authenticate"] == "Bearer"
    assert r.json()["code"] == "UNAUTHENTICATED"
    _sem_vazamento(r.json())


@pytest.mark.parametrize("cabecalho", [
    "Bearer",
    "Bearer ",
    "Basic dXN1YXJpbzpzZW5oYQ==",
    "Token abc.def.ghi",
    "bearerabc.def.ghi",
    "Bearer abc def",
])
def test_cabecalho_malformado_e_401(cliente, cabecalho):
    r = cliente.get("/api/v1/me", headers={"Authorization": cabecalho})
    assert r.status_code == 401
    _sem_vazamento(r.json())


def test_bearer_sem_verificador_e_503_e_nunca_200(cliente):
    # Token com cara de JWT, assinatura qualquer. Sem verificador, a
    # API não sabe se ele vale — e quem não sabe, recusa.
    r = cliente.get("/api/v1/me",
                    headers={"Authorization": "Bearer aaa.bbb.ccc"})
    assert r.status_code == 503
    assert r.json()["code"] == "AUTH_UNAVAILABLE"
    _sem_vazamento(r.json())


def test_modo_aberto_nao_abre_a_api(config):
    # GOVDOCS_MODO_ABERTO é do Streamlit. Mesmo em desenvolvimento, onde
    # a configuração aceita a variável, ela não tem efeito aqui.
    config_dev = carregar({"APP_ENV": "development",
                           "GOVDOCS_MODO_ABERTO": "1"})
    cliente = TestClient(criar_app(config_dev), raise_server_exceptions=False)
    assert cliente.get("/api/v1/me").status_code == 401


def test_token_recusado_pelo_verificador_e_401(config):
    class Recusa:
        def verificar(self, token):
            raise TokenRecusado("assinatura")

    cliente = TestClient(criar_app(config, verificador=Recusa()),
                         raise_server_exceptions=False)
    r = cliente.get("/api/v1/me", headers={"Authorization": "Bearer x.y.z"})
    assert r.status_code == 401
    assert "assinatura" not in r.text


def test_verificador_quebrado_nao_vira_acesso(config):
    # Falha inesperada do verificador (rede, JWKS fora) é 500 com
    # envelope — nunca 200, e nunca o texto da exceção na resposta.
    class Quebrado:
        def verificar(self, token):
            raise RuntimeError("https://x.supabase.co?apikey=segredo")

    cliente = TestClient(criar_app(config, verificador=Quebrado()),
                         raise_server_exceptions=False)
    r = cliente.get("/api/v1/me", headers={"Authorization": "Bearer x.y.z"})
    assert r.status_code == 500
    assert r.json()["code"] == "INTERNAL_ERROR"
    assert "apikey" not in r.text and "supabase" not in r.text
    assert r.headers["x-request-id"] == r.json()["request_id"]
