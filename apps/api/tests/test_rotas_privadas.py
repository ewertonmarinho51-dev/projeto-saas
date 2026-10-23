"""
Toda rota sob /api/v1 exige identidade — prova MECÂNICA e por COMPORTAMENTO.

Revisão humana esquece. Esta prova percorre o OpenAPI da aplicação e
CHAMA cada operação de /api/v1 sem credencial: tem de voltar 401. Vale
também para as rotas que entrarem depois deste PR.

Por comportamento, e não lendo a árvore de dependências: o FastAPI 0.15x
passou a guardar roteadores incluídos num tipo interno preguiçoso, e a
primeira versão desta prova — que inspecionava `app.routes` — passou a
ver zero rotas. Uma prova que depende de detalhe interno da biblioteca
quebra calada na próxima versão; a chamada HTTP não.
"""

import re
import uuid

from fastapi.testclient import TestClient

from govconect_api.main import criar_app

# Rotas públicas, com nome. Acrescentar aqui é decisão de segurança e
# aparece no diff — que é a ideia.
# `/health/metrics` (P06): contadores por modelo de rota, sem usuário nem
# município; a API não é publicada pelo Caddy.
PUBLICAS = {"/health/live", "/health/ready", "/health/metrics"}

_PARAMETRO = re.compile(r"\{[^}]+\}")


def _operacoes(app):
    for caminho, operacoes in app.openapi()["paths"].items():
        concreto = _PARAMETRO.sub(str(uuid.uuid4()), caminho)
        for metodo in operacoes:
            yield caminho, metodo.upper(), concreto


def rotas_que_nao_recusam(app, cabecalhos=None, esperado=401):
    cliente = TestClient(app, raise_server_exceptions=False)
    falhas = []
    for caminho, metodo, concreto in _operacoes(app):
        if not caminho.startswith("/api/v1"):
            continue
        r = cliente.request(metodo, concreto, headers=cabecalhos or {}, json={})
        if r.status_code != esperado:
            falhas.append(f"{metodo} {caminho} -> {r.status_code}")
    return falhas


def test_toda_rota_v1_recusa_sem_credencial(config):
    app = criar_app(config)
    assert any(c.startswith("/api/v1") for c, _, _ in _operacoes(app))
    assert rotas_que_nao_recusam(app) == []


def test_toda_rota_v1_recusa_sem_verificador(config):
    # Com bearer bem formado e sem verificador: 503, nunca 2xx.
    app = criar_app(config)
    assert rotas_que_nao_recusam(
        app, {"Authorization": "Bearer aaa.bbb.ccc"}, esperado=503) == []


def test_fora_de_v1_so_existem_as_publicas_declaradas(config):
    caminhos = set(criar_app(config).openapi()["paths"])
    fora = {c for c in caminhos if not c.startswith("/api/v1")}
    assert fora <= PUBLICAS, f"rota pública não declarada: {fora - PUBLICAS}"


def test_rota_nova_no_roteador_v1_nasce_protegida(config):
    # A guarda mora no ROTEADOR: quem acrescentar rota em `_rotas_v1`
    # sem pedir identidade continua protegido.
    from fastapi import FastAPI

    from govconect_api import main

    roteador = main._rotas_v1()

    @roteador.get("/esquecida")
    def esquecida():
        return {"vazou": True}

    app = FastAPI()
    app.state.verificador_de_token = None
    main.erros.instalar(app)
    app.include_router(roteador)
    r = TestClient(app, raise_server_exceptions=False).get("/api/v1/esquecida")
    assert r.status_code == 401


def test_a_prova_pegaria_rota_desprotegida(config):
    # A prova tem dente? Uma rota v1 montada sem a guarda tem de aparecer.
    app = criar_app(config)

    @app.get("/api/v1/vazamento/{id}")
    def vazamento(id: str):
        return {"id": id}

    assert rotas_que_nao_recusam(app) == ["GET /api/v1/vazamento/{id} -> 200"]
