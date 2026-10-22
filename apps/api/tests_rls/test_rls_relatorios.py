"""
Emissão de relatório contra a pilha real (P04d).

Domínio verdadeiro, banco verdadeiro, RLS verdadeiro, flags lidas pela
`flags_do_app()` (0033). O que se prova:

* sem ciência desta versão da cesta, o WORKER recusa — o pedido sozinho
  não emite;
* a ciência registrada pelo dono destrava; o arquivo sai (DOCX do
  relatório visual, sem LibreOffice), a emissão fica no banco (0029) com
  o hash do arquivo entregue e o evento com o ator verdadeiro;
* cesta que muda depois da ciência a invalida;
* colega lê o preparo mas não registra ciência nem baixa o arquivo alheio;
  outro município nem vê;
* com Redis (`REDIS_URL`), o ciclo inteiro por Celery de verdade.
"""

from __future__ import annotations

import hashlib
import os
import subprocess
import sys
import time
import uuid
from pathlib import Path

import pytest

RAIZ_API = Path(__file__).resolve().parent.parent


@pytest.fixture
def pesquisa(pilha):
    import pilha as modulo_pilha
    from src import db

    pid = modulo_pilha.semear_emissao(pilha)
    db._config_app_inteira.clear()      # flags recém-ligadas valem já
    return pid


class FilaGuardada:
    def __init__(self):
        self.avisos = []

    def enfileirar(self, **aviso):
        self.avisos.append(aviso)


def _api(pilha, **extra):
    from fastapi.testclient import TestClient

    from govconect_api.artefatos import DepositoMemoria
    from govconect_api.config import carregar
    from govconect_api.main import criar_app

    config = carregar({"APP_ENV": "test", "SUPABASE_URL": pilha.url, "SUPABASE_KEY": pilha.anon,
                       "PRICE_RESEARCH_ENABLED": "1", "GOVCONECT_LIMITE_POR_MINUTO": "10000",
                       **extra})
    opcoes = {} if "REDIS_URL" in extra else {"fila": FilaGuardada(),
                                              "deposito": DepositoMemoria()}
    return TestClient(criar_app(config, **opcoes), raise_server_exceptions=False)


def _h(conta, chave=None):
    return {"Authorization": f"Bearer {conta.token}",
            "Idempotency-Key": chave or f"rel-{uuid.uuid4().hex}"}


def _processar(api, pilha):
    from govconect_api.relatorios import processar_relatorio
    from govconect_api.supabase_rest import ClienteRest

    aviso = api.app.state.fila.avisos.pop()
    aviso.pop("tarefa")
    return processar_relatorio(rest=ClienteRest(pilha.url, pilha.anon),
                               deposito=api.app.state.deposito, **aviso)


def _pedir(api, pid, conta, tipo="cotacao", formato="docx"):
    r = api.post(f"/api/v1/precos/pesquisas/{pid}/relatorios", headers=_h(conta),
                 json={"tipo": tipo, "formato": formato})
    assert r.status_code == 202, r.text
    return r.json()["id"]


def test_sem_ciencia_o_worker_recusa_e_com_ciencia_emite(pilha, pesquisa):
    import psycopg

    api, a1 = _api(pilha), pilha.contas["a1"]
    preparo = api.get(f"/api/v1/precos/pesquisas/{pesquisa}/emissao", headers=_h(a1)).json()
    assert preparo["disponivel"] and preparo["requer_ciencia"], preparo
    assert preparo["pendencias"] and preparo["ciencia"] is None
    assert preparo["pode_registrar_ciencia"]

    recusado = _pedir(api, pesquisa, a1)
    assert _processar(api, pilha) == "failed"
    job = api.get(f"/api/v1/jobs/{recusado}", headers=_h(a1)).json()
    assert job["erro_codigo"] == "CIENCIA_REQUIRED"

    r = api.post(f"/api/v1/precos/pesquisas/{pesquisa}/ciencia", headers=_h(a1),
                 json={"assinatura": preparo["assinatura"]})
    assert r.status_code == 201, r.text
    depois = api.get(f"/api/v1/precos/pesquisas/{pesquisa}/emissao", headers=_h(a1)).json()
    assert depois["ciencia"] and depois["assinatura"] == preparo["assinatura"]

    job_id = _pedir(api, pesquisa, a1)
    assert _processar(api, pilha) == "succeeded"
    job = api.get(f"/api/v1/jobs/{job_id}", headers=_h(a1)).json()
    assert job["estado"] == "succeeded" and job["resultado"]["nome"].endswith(".docx")
    assert job["resultado"]["registrado"] is True

    baixado = api.get(f"/api/v1/jobs/{job_id}/artefato", headers=_h(a1))
    assert baixado.status_code == 200 and baixado.content[:2] == b"PK"
    sha = hashlib.sha256(baixado.content).hexdigest()
    assert job["resultado"]["sha256"] == sha

    with psycopg.connect(pilha.dsn) as c:
        emissoes = c.execute(
            "select tipo, formato, hash_arquivo from public.pesquisa_preco_emissoes "
            "where pesquisa_id=%s", (pesquisa,)).fetchall()
        assert emissoes == [("completo", "docx", sha)], "o registro é do byte entregue"
        atores = c.execute(
            "select ator::text from public.pesquisa_preco_eventos where pesquisa_id=%s "
            "and tipo='relatorio_emitido'", (pesquisa,)).fetchall()
        assert atores == [(a1.auth_user_id,)]

    # Outro gerador (memória analítica XLSX) com a mesma ciência.
    _pedir(api, pesquisa, a1, tipo="analitico", formato="xlsx")
    assert _processar(api, pilha) == "succeeded"


def test_cesta_que_muda_invalida_a_ciencia(pilha, pesquisa):
    import psycopg

    api, a1 = _api(pilha), pilha.contas["a1"]
    assinatura = api.get(f"/api/v1/precos/pesquisas/{pesquisa}/emissao",
                         headers=_h(a1)).json()["assinatura"]
    with psycopg.connect(pilha.dsn, autocommit=True) as c:
        c.execute("update public.pesquisa_preco_referencias set status='excluded' "
                  "where item_id in (select id from public.pesquisa_preco_itens "
                  "where pesquisa_id=%s)", (pesquisa,))
    r = api.post(f"/api/v1/precos/pesquisas/{pesquisa}/ciencia", headers=_h(a1),
                 json={"assinatura": assinatura})
    assert r.status_code == 409 and r.json()["code"] == "CIENCIA_DESATUALIZADA"


def test_colega_le_mas_nao_registra_ciencia_nem_baixa(pilha, pesquisa):
    api, a1, colega = _api(pilha), pilha.contas["a1"], pilha.contas["a1_colega"]
    preparo = api.get(f"/api/v1/precos/pesquisas/{pesquisa}/emissao", headers=_h(colega))
    assert preparo.status_code == 200 and preparo.json()["pode_registrar_ciencia"] is False
    r = api.post(f"/api/v1/precos/pesquisas/{pesquisa}/ciencia", headers=_h(colega),
                 json={"assinatura": preparo.json()["assinatura"]})
    assert r.status_code == 403

    api.post(f"/api/v1/precos/pesquisas/{pesquisa}/ciencia", headers=_h(a1),
             json={"assinatura": preparo.json()["assinatura"]})
    job_id = _pedir(api, pesquisa, a1, tipo="analitico", formato="xlsx")
    assert _processar(api, pilha) == "succeeded"
    assert api.get(f"/api/v1/jobs/{job_id}/artefato", headers=_h(colega)).status_code == 404
    assert api.get(f"/api/v1/jobs/{job_id}/artefato", headers=_h(a1)).status_code == 200


def test_outro_municipio_nem_ve(pilha, pesquisa):
    api, b1 = _api(pilha), pilha.contas["b1"]
    assert api.get(f"/api/v1/precos/pesquisas/{pesquisa}/emissao",
                   headers=_h(b1)).status_code == 404
    r = api.post(f"/api/v1/precos/pesquisas/{pesquisa}/relatorios", headers=_h(b1),
                 json={"tipo": "cotacao", "formato": "docx"})
    assert r.status_code == 404


def test_celery_e_redis_de_verdade(pilha, pesquisa):
    redis_url = os.getenv("REDIS_URL", "")
    if not redis_url:
        if os.getenv("GOVCONECT_EXIGIR_REDIS") == "1":
            pytest.fail("REDIS_URL exigida e ausente")
        pytest.skip("sem Redis (roda no job api-rls do CI)")
    ambiente = {**os.environ, "APP_ENV": "test", "SUPABASE_URL": pilha.url,
                "SUPABASE_KEY": pilha.anon, "REDIS_URL": redis_url,
                "PRICE_RESEARCH_ENABLED": "1",
                "PYTHONPATH": os.pathsep.join([str(RAIZ_API), str(RAIZ_API.parent.parent)])}
    worker = subprocess.Popen(
        [sys.executable, "-m", "celery", "-A", "govconect_api.fila:celery", "worker",
         "--pool=solo", "--concurrency=1", "--loglevel=WARNING", "--without-gossip",
         "--without-mingle"], cwd=RAIZ_API, env=ambiente,
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    try:
        api, a1 = _api(pilha, REDIS_URL=redis_url), pilha.contas["a1"]
        assinatura = api.get(f"/api/v1/precos/pesquisas/{pesquisa}/emissao",
                             headers=_h(a1)).json()["assinatura"]
        assert api.post(f"/api/v1/precos/pesquisas/{pesquisa}/ciencia", headers=_h(a1),
                        json={"assinatura": assinatura}).status_code == 201
        job_id = _pedir(api, pesquisa, a1, tipo="analitico", formato="xlsx")
        final = None
        for _ in range(120):
            final = api.get(f"/api/v1/jobs/{job_id}", headers=_h(a1)).json()
            if final["estado"] in ("succeeded", "failed"):
                break
            time.sleep(0.5)
        assert final and final["estado"] == "succeeded", final
        baixado = api.get(f"/api/v1/jobs/{job_id}/artefato", headers=_h(a1))
        assert baixado.status_code == 200 and baixado.content[:2] == b"PK"
        assert hashlib.sha256(baixado.content).hexdigest() == final["resultado"]["sha256"]
    finally:
        worker.terminate()
        try:
            saida, _ = worker.communicate(timeout=20)
        except subprocess.TimeoutExpired:
            worker.kill()
            saida, _ = worker.communicate()
        assert pilha.contas["a1"].token not in (saida or "")
