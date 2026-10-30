"""
GovBot contra Postgres + GoTrue + PostgREST reais: o processo do contexto
é lido com o token do usuário, e o RLS da 0001 decide quem o vê. O motor de
IA é falso (sem rede); o que se prova é a fronteira de dados.
"""

from __future__ import annotations

import json
import uuid

import pytest


def _h(conta, **extra):
    return {"Authorization": f"Bearer {conta.token}", **extra}


@pytest.fixture(scope="module")
def api_govbot(pilha):
    from fastapi.testclient import TestClient

    from govconect_api.config import carregar
    from govconect_api.main import criar_app

    config = carregar({"APP_ENV": "test", "SUPABASE_URL": pilha.url,
                       "SUPABASE_KEY": pilha.anon, "GOVCONECT_GOVBOT": "1",
                       "GOVCONECT_LIMITE_POR_MINUTO": "10000"})
    app = criar_app(config)
    app.state.govbot_chamar = lambda *a, **k: json.dumps({
        "intent": "explain_current", "response": "Resposta de teste.",
        "target": None, "payload": {}, "sources": []})
    app.state.govbot_buscar = lambda *a, **k: []
    return TestClient(app, raise_server_exceptions=False)


@pytest.fixture(scope="module")
def processo_a1(api_govbot, pilha):
    r = api_govbot.post("/api/v1/processos",
                        headers=_h(pilha.contas["a1"], **{"Idempotency-Key": f"k-{uuid.uuid4().hex}"}),
                        json={"orgao": "Secretaria de Saúde", "objeto": "Cadeiras GovBot"})
    assert r.status_code == 201, r.text
    return r.json()["id"]


@pytest.mark.parametrize("rotulo, esperado", [
    ("a1", 200),          # dono
    ("a1_colega", 200),   # mesma secretaria
    ("a2", 404),          # outra secretaria do mesmo município
    ("b1", 404),          # outro município
])
def test_contexto_do_processo_segue_o_rls(api_govbot, pilha, processo_a1, rotulo, esperado):
    r = api_govbot.post("/api/v1/govbot/perguntas", headers=_h(pilha.contas[rotulo]),
                        json={"pergunta": "O que está faltando?", "processo_id": processo_a1})
    assert r.status_code == esperado, r.text
    if esperado == 200:
        assert r.json()["acao"] == "show_missing_information"


def test_sem_processo_responde_para_qualquer_conta_ativa(api_govbot, pilha):
    r = api_govbot.post("/api/v1/govbot/perguntas", headers=_h(pilha.contas["b1"]),
                        json={"pergunta": "O que é o ETP?"})
    assert r.status_code == 200, r.text
    assert r.json()["resposta"] == "Resposta de teste."
