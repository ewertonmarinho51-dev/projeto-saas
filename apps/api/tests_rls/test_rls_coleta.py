"""
Coleta assíncrona contra a pilha real.

Dois níveis:

* `processar_job` direto (sem broker): domínio verdadeiro, banco verdadeiro,
  RLS verdadeiro, com `fontes=[]` — o fluxo inteiro sem sair para PNCP e
  Compras.gov, que não são do CI;
* Celery + Redis de verdade (só com `REDIS_URL`; no job `api-rls` é
  obrigatório): a API põe o aviso na fila, um worker real o consome, e a
  consulta do job vê o fim.
"""

from __future__ import annotations

import os
import subprocess
import sys
import time
import uuid
from pathlib import Path

import pytest

RAIZ_API = Path(__file__).resolve().parent.parent


@pytest.fixture
def pesquisa_pendente(pilha):
    import pilha as modulo_pilha

    return modulo_pilha.semear_coleta(pilha)


def _api(pilha, **extra):
    from fastapi.testclient import TestClient

    from govconect_api.config import carregar
    from govconect_api.main import criar_app

    config = carregar({"APP_ENV": "test", "SUPABASE_URL": pilha.url, "SUPABASE_KEY": pilha.anon,
                       "PRICE_RESEARCH_ENABLED": "1", "GOVCONECT_LIMITE_POR_MINUTO": "10000",
                       "GOVCONECT_FONTES_COLETA": "nenhuma", **extra})
    return TestClient(criar_app(config, **({} if "REDIS_URL" in extra else {"fila": FilaGuardada()})),
                      raise_server_exceptions=False)


class FilaGuardada:
    def __init__(self):
        self.avisos = []

    def enfileirar(self, **aviso):
        self.avisos.append(aviso)


def _h(conta, chave=None):
    return {"Authorization": f"Bearer {conta.token}",
            "Idempotency-Key": chave or f"coleta-{uuid.uuid4().hex}"}


def _estados_dos_itens(pilha, pid):
    import psycopg

    with psycopg.connect(pilha.dsn) as c:
        return [r[0] for r in c.execute(
            "select estado from public.pesquisa_preco_itens where pesquisa_id=%s order by numero",
            (pid,)).fetchall()]


def test_worker_real_processa_todos_os_itens(pilha, pesquisa_pendente):
    from govconect_api.coleta import processar_job
    from govconect_api.supabase_rest import ClienteRest

    api = _api(pilha)
    a1 = pilha.contas["a1"]
    r = api.post(f"/api/v1/precos/pesquisas/{pesquisa_pendente}/coleta", headers=_h(a1), json={})
    assert r.status_code == 202, r.text
    job = r.json()
    assert job["estado"] == "queued" and job["total"] == 2
    (aviso,) = api.app.state.fila.avisos

    rest = ClienteRest(pilha.url, pilha.anon)
    final = processar_job(rest=rest, fontes=[], **aviso)
    assert final == "succeeded"
    consulta = api.get(f"/api/v1/jobs/{job['id']}", headers=_h(a1)).json()
    assert (consulta["estado"], consulta["feitos"], consulta["total"], consulta["progresso"]) == \
        ("succeeded", 2, 2, 100)
    # O domínio andou com os itens (saíram de pendente): não é o job que diz.
    assert "pending" not in _estados_dos_itens(pilha, pesquisa_pendente)

    # Aviso repetido (fila reentregou): não refaz nada.
    assert processar_job(rest=rest, fontes=[], **aviso) == "succeeded"


@pytest.mark.parametrize("rotulo", ["a1_colega", "b1", "admin_a"])
def test_job_so_o_dono_ve(pilha, pesquisa_pendente, rotulo):
    api = _api(pilha)
    r = api.post(f"/api/v1/precos/pesquisas/{pesquisa_pendente}/coleta",
                 headers=_h(pilha.contas["a1"]), json={})
    assert r.status_code == 202, r.text
    assert api.get(f"/api/v1/jobs/{r.json()['id']}",
                   headers=_h(pilha.contas[rotulo])).status_code == 404


def test_colega_nao_pede_coleta_da_pesquisa_alheia(pilha, pesquisa_pendente):
    r = _api(pilha).post(f"/api/v1/precos/pesquisas/{pesquisa_pendente}/coleta",
                         headers=_h(pilha.contas["a1_colega"]), json={})
    assert r.status_code == 403


def test_mesma_chave_nao_cria_dois_jobs(pilha, pesquisa_pendente):
    import psycopg

    api = _api(pilha)
    chave = f"coleta-{uuid.uuid4().hex}"
    a1 = pilha.contas["a1"]
    primeiro = api.post(f"/api/v1/precos/pesquisas/{pesquisa_pendente}/coleta", headers=_h(a1, chave), json={})
    segundo = api.post(f"/api/v1/precos/pesquisas/{pesquisa_pendente}/coleta", headers=_h(a1, chave), json={})
    assert (primeiro.status_code, segundo.status_code) == (202, 200)
    assert primeiro.json()["id"] == segundo.json()["id"]
    assert len(api.app.state.fila.avisos) == 1
    with psycopg.connect(pilha.dsn) as c:
        assert c.execute("select count(*) from public.api_jobs where idempotency_key=%s",
                         (chave,)).fetchone() == (1,)


def test_celery_e_redis_de_verdade(pilha, pesquisa_pendente):
    redis_url = os.getenv("REDIS_URL", "")
    if not redis_url:
        if os.getenv("GOVCONECT_EXIGIR_REDIS") == "1":
            pytest.fail("REDIS_URL exigida e ausente")
        pytest.skip("sem Redis (roda no job api-rls do CI)")
    ambiente = {**os.environ, "APP_ENV": "test", "SUPABASE_URL": pilha.url,
                "SUPABASE_KEY": pilha.anon, "REDIS_URL": redis_url,
                "GOVCONECT_FONTES_COLETA": "nenhuma", "PRICE_RESEARCH_ENABLED": "1",
                "PYTHONPATH": os.pathsep.join([str(RAIZ_API), str(RAIZ_API.parent.parent)])}
    worker = subprocess.Popen(
        [sys.executable, "-m", "celery", "-A", "govconect_api.fila:celery", "worker",
         "--pool=solo", "--concurrency=1", "--loglevel=WARNING", "--without-gossip",
         "--without-mingle"], cwd=RAIZ_API, env=ambiente,
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    try:
        api = _api(pilha, REDIS_URL=redis_url)
        a1 = pilha.contas["a1"]
        r = api.post(f"/api/v1/precos/pesquisas/{pesquisa_pendente}/coleta", headers=_h(a1), json={})
        assert r.status_code == 202, r.text
        job_id = r.json()["id"]
        final = None
        for _ in range(120):
            final = api.get(f"/api/v1/jobs/{job_id}", headers=_h(a1)).json()
            if final["estado"] in ("succeeded", "failed"):
                break
            time.sleep(0.5)
        assert final and final["estado"] == "succeeded", final
        assert final["feitos"] == final["total"] == 2
    finally:
        worker.terminate()
        try:
            saida, _ = worker.communicate(timeout=20)
        except subprocess.TimeoutExpired:
            worker.kill()
            saida, _ = worker.communicate()
        # O token não pode aparecer no log do worker.
        assert pilha.contas["a1"].token not in (saida or "")
