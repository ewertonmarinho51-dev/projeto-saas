import json

from fastapi.testclient import TestClient

from govconect_api.config import carregar
from govconect_api.main import criar_app


def test_liveness_responde_sem_dependencia(cliente):
    r = cliente.get("/health/live")
    assert r.status_code == 200
    assert r.json() == {"status": "ok"}


def test_readiness_e_503_sem_verificador(cliente):
    # Honesto: no P01 a API não sabe autenticar, logo não está pronta
    # para tráfego. O proxy não deve mandar usuário para ela.
    r = cliente.get("/health/ready")
    assert r.status_code == 503
    assert r.json() == {"status": "not_ready",
                        "checks": {"configuracao": "ok",
                                   "verificador_de_token": "ausente"}}


def test_readiness_nao_expoe_url_nem_chave(config):
    r = TestClient(criar_app(config)).get("/health/ready")
    assert "supabase" not in r.text.lower()
    assert "exemplo-staging" not in r.text


def test_readiness_pronta_com_verificador(config):
    class Qualquer:
        def verificar(self, token):  # pragma: no cover — não chamado
            raise AssertionError

    r = TestClient(criar_app(config, verificador=Qualquer())).get("/health/ready")
    assert r.status_code == 200
    assert r.json()["status"] == "ready"


def test_request_id_gerado_e_devolvido(cliente):
    r = cliente.get("/health/live")
    assert len(r.headers["x-request-id"]) == 32


def test_request_id_do_proxy_e_aceito_se_bem_formado(cliente):
    r = cliente.get("/api/v1/me", headers={"X-Request-ID": "caddy-abc12345"})
    assert r.headers["x-request-id"] == "caddy-abc12345"
    assert r.json()["request_id"] == "caddy-abc12345"


def test_request_id_malformado_e_substituido(cliente):
    r = cliente.get("/health/live",
                    headers={"X-Request-ID": "x\ninjetado: sim"})
    assert r.headers["x-request-id"] != "x\ninjetado: sim"
    assert len(r.headers["x-request-id"]) == 32


def test_respostas_nao_sao_cacheaveis(cliente):
    for caminho in ("/health/live", "/api/v1/me", "/rota-inexistente"):
        r = cliente.get(caminho)
        assert r.headers["cache-control"] == "no-store", caminho
        assert r.headers["x-content-type-options"] == "nosniff", caminho


def test_404_usa_envelope(cliente):
    r = cliente.get("/rota-inexistente")
    assert r.status_code == 404
    assert r.json()["code"] == "NOT_FOUND"


def test_validacao_nao_ecoa_o_que_recebeu(config):
    from fastapi import Body

    app = criar_app(config)

    @app.post("/eco")
    def eco(valor: int = Body(..., embed=True)):
        return {}

    r = TestClient(app).post("/eco", json={"valor": "CONTEUDO-SIGILOSO"})
    assert r.status_code == 422
    assert "CONTEUDO-SIGILOSO" not in r.text
    assert r.json()["fields"][0]["loc"] == ["body", "valor"]


def test_documentacao_interativa_so_em_desenvolvimento():
    prod = carregar({"APP_ENV": "production",
                     "SUPABASE_URL": "https://prod.exemplo.co",
                     "SUPABASE_KEY": "chave-publicavel-de-teste"})
    cliente = TestClient(criar_app(prod))
    assert cliente.get("/docs").status_code == 404
    assert cliente.get("/openapi.json").status_code == 404


def test_cors_so_para_origem_listada():
    config = carregar({"APP_ENV": "staging",
                       "SUPABASE_URL": "https://staging.exemplo.co",
                       "SUPABASE_KEY": "chave-publicavel-de-teste",
                       "GOVCONECT_CORS_ORIGINS": "https://app.staging.exemplo.co"})
    cliente = TestClient(criar_app(config))
    preflight = {"Access-Control-Request-Method": "GET",
                 "Access-Control-Request-Headers": "authorization"}
    ok = cliente.options("/api/v1/me", headers={
        "Origin": "https://app.staging.exemplo.co", **preflight})
    assert ok.headers.get("access-control-allow-origin") == \
        "https://app.staging.exemplo.co"
    estranho = cliente.options("/api/v1/me", headers={
        "Origin": "https://atacante.exemplo", **preflight})
    assert "access-control-allow-origin" not in estranho.headers


def test_sem_origens_configuradas_nao_ha_cors(cliente):
    r = cliente.get("/health/live", headers={"Origin": "https://qualquer.exemplo"})
    assert "access-control-allow-origin" not in r.headers
    json.dumps(r.json())
