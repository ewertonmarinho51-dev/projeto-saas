"""
Coleta assíncrona: o pedido (202 + job), a consulta e o worker.

PostgREST simulado e domínio substituído: aqui se prova a orquestração
— job gravado antes da fila, idempotência, fila fora do ar, progresso,
parada antes de o token vencer, aviso repetido sem refazer, token fora
do log. O ciclo com banco real é `tests_rls/test_rls_coleta.py`.
"""

import base64
import json
import time

import pytest
from fastapi.testclient import TestClient

from govconect_api import coleta
from govconect_api.config import carregar
from govconect_api.main import criar_app
from govconect_api.verificador import VerificadorSupabase
from src import db
from src.precos import cotacoes
from src.precos import repositorio as repo

from apoio_jwt import EMISSOR, TENANT_A, USUARIO_A, Emissor, PostgrestFalso

P = "dddddddd-0000-4000-8000-000000000001"
JOB = "abababab-0000-4000-8000-000000000001"


class FilaFalsa:
    def __init__(self, quebrar=False):
        self.avisos, self.quebrar = [], quebrar

    def enfileirar(self, **aviso):
        if self.quebrar:
            raise ConnectionError("redis fora")
        self.avisos.append(aviso)


def _job(**extra):
    base = {"id": JOB, "tipo": "coleta_precos", "recurso_id": P, "estado": "queued",
            "feitos": 0, "total": 3, "tentativas": 0, "erro_codigo": "", "parametros": {"modo": "manual"},
            "criado_em": "2026-10-22T18:00:00+00:00", "iniciado_em": None, "concluido_em": None}
    return {**base, **extra}


@pytest.fixture
def emissor():
    return Emissor()


@pytest.fixture
def banco():
    b = PostgrestFalso()
    b.responder("GET", "pesquisas_preco", 200, [{"id": P, "auth_user_id": USUARIO_A, "estado": "review"}])
    b.responder("GET", "pesquisa_preco_itens", 200, [{"id": "i1"}, {"id": "i2"}, {"id": "i3"}])
    return b


def _api(emissor, banco, fila, precos=True):
    config = carregar({"APP_ENV": "test", "SUPABASE_URL": "https://exemplo-staging.supabase.co",
                       "SUPABASE_KEY": "chave-publicavel-de-teste",
                       "PRICE_RESEARCH_ENABLED": "1" if precos else "0"})
    rest = banco.cliente()
    return TestClient(criar_app(config, rest=rest, fila=fila, verificador=VerificadorSupabase(
        emissor=EMISSOR, rest=rest, chave_para=emissor.chave_para)), raise_server_exceptions=False)


def _h(emissor, chave="coleta-0001"):
    return {"Authorization": f"Bearer {emissor.token()}", "Idempotency-Key": chave}


URL = f"/api/v1/precos/pesquisas/{P}/coleta"


def test_pedido_grava_o_job_poe_na_fila_e_responde_202(emissor, banco):
    banco.responder("POST", "api_jobs", 201, [_job()])
    fila = FilaFalsa()
    r = _api(emissor, banco, fila).post(URL, headers=_h(emissor), json={"modo": "manual"})
    assert r.status_code == 202, r.text
    assert r.headers["location"] == f"/api/v1/jobs/{JOB}"
    assert r.json()["estado"] == "queued" and r.json()["total"] == 3
    gravado = banco.corpo(next(c for c in banco.chamadas if c.method == "POST"))
    assert (gravado["tenant_id"], gravado["auth_user_id"], gravado["total"],
            gravado["idempotency_key"]) == (TENANT_A, USUARIO_A, 3, "coleta-0001")
    (aviso,) = fila.avisos
    assert aviso["job_id"] == JOB and aviso["tenant_id"] == TENANT_A and aviso["token"]


def test_mesma_chave_devolve_o_mesmo_job_sem_nova_fila(emissor, banco):
    banco.responder("POST", "api_jobs", 409, {"code": "23505"})
    banco.responder("GET", "api_jobs", 200, [_job(estado="running", feitos=1)])
    fila = FilaFalsa()
    r = _api(emissor, banco, fila).post(URL, headers=_h(emissor), json={})
    assert r.status_code == 200 and r.headers["idempotent-replayed"] == "true"
    assert r.json()["progresso"] == 33
    assert fila.avisos == []


def test_fila_fora_do_ar_e_503_e_o_job_fica_registrado_como_falha(emissor, banco):
    banco.responder("POST", "api_jobs", 201, [_job()])
    r = _api(emissor, banco, FilaFalsa(quebrar=True)).post(URL, headers=_h(emissor), json={})
    assert r.status_code == 503 and r.json()["code"] == "QUEUE_UNAVAILABLE"
    patch = next(c for c in banco.chamadas if c.method == "PATCH")
    assert banco.corpo(patch)["erro_codigo"] == "QUEUE_UNAVAILABLE"
    assert "redis" not in r.text


def test_sem_fila_configurada_tambem_e_503(emissor, banco):
    banco.responder("POST", "api_jobs", 201, [_job()])
    r = _api(emissor, banco, None).post(URL, headers=_h(emissor), json={})
    assert r.status_code == 503


def test_so_dono_ou_admin_pede_coleta(emissor, banco):
    banco.respostas[("GET", "pesquisas_preco")] = []
    banco.responder("GET", "pesquisas_preco", 200,
                    [{"id": P, "auth_user_id": "dddddddd-0000-4000-8000-000000000009"}])
    r = _api(emissor, banco, FilaFalsa()).post(URL, headers=_h(emissor), json={})
    assert r.status_code == 403
    assert not any(c.method == "POST" for c in banco.chamadas)


@pytest.mark.parametrize("cabecalhos, corpo, status", [
    ({"Idempotency-Key": "curta"}, {}, 400),
    ({}, {"modo": "magico"}, 422),
    ({}, {"modo": "manual", "fontes": ["x"]}, 422),
])
def test_pedido_invalido(emissor, banco, cabecalhos, corpo, status):
    r = _api(emissor, banco, FilaFalsa()).post(URL, headers={**_h(emissor), **cabecalhos}, json=corpo)
    assert r.status_code == status


def test_flag_desligada_e_404(emissor, banco):
    r = _api(emissor, banco, FilaFalsa(), precos=False).post(URL, headers=_h(emissor), json={})
    assert r.status_code == 404


def test_consulta_do_job(emissor, banco):
    banco.responder("GET", "api_jobs", 200, [_job(estado="running", feitos=2)])
    r = _api(emissor, banco, FilaFalsa()).get(f"/api/v1/jobs/{JOB}", headers=_h(emissor))
    assert r.status_code == 200 and r.json()["progresso"] == 66
    assert banco.chamadas[-1].url.params["tenant_id"] == f"eq.{TENANT_A}"


# ---------------------------------------------------------------------------
# Worker
# ---------------------------------------------------------------------------
def _token(exp_em: float) -> str:
    carga = base64.urlsafe_b64encode(json.dumps({"exp": exp_em}).encode()).decode().rstrip("=")
    return f"cabecalho.{carga}.assinatura"


@pytest.fixture
def dominio(monkeypatch):
    estado = {"restantes": [2, 1, 0], "chamadas": 0, "erro": None}

    def passo(ctx, pesquisa_id, *, modo, tamanho, ja_tentados, **opcoes):
        estado["chamadas"] += 1
        estado["opcoes"] = opcoes
        if estado["erro"]:
            raise estado["erro"]
        ja_tentados.add(f"i{estado['chamadas']}")
        return [], estado["restantes"].pop(0)

    monkeypatch.setattr(cotacoes, "pesquisar_em_lote", passo)
    monkeypatch.setattr(repo, "obter_pesquisa", lambda pid: {"id": pid, "estado": "review"})
    return estado


def _processar(banco, token, **kw):
    return coleta.processar_job(job_id=JOB, token=token, tenant_id=TENANT_A,
                                auth_user_id=USUARIO_A, secretaria_id=None,
                                rest=banco.cliente(), **kw)


def _patches(banco):
    return [banco.corpo(c) for c in banco.chamadas if c.method == "PATCH"]


def test_worker_processa_ate_o_fim_e_registra_progresso(banco, dominio):
    banco.responder("GET", "api_jobs", 200, [_job()])
    assert _processar(banco, _token(time.time() + 3600), fontes=[]) == "succeeded"
    corpos = _patches(banco)
    assert corpos[0]["estado"] == "running" and corpos[0]["tentativas"] == 1
    assert [c["feitos"] for c in corpos[1:4]] == [1, 2, 3]
    assert corpos[-1]["estado"] == "succeeded"
    assert dominio["opcoes"] == {"fontes": []}


def test_worker_para_antes_de_o_token_vencer(banco, dominio):
    banco.responder("GET", "api_jobs", 200, [_job()])
    assert _processar(banco, _token(time.time() + 30)) == "failed"
    assert _patches(banco)[-1]["erro_codigo"] == "SESSION_EXPIRED"
    assert dominio["chamadas"] == 0


def test_aviso_repetido_de_job_concluido_nao_refaz_nada(banco, dominio):
    banco.responder("GET", "api_jobs", 200, [_job(estado="succeeded")])
    assert _processar(banco, _token(time.time() + 3600)) == "succeeded"
    assert _patches(banco) == [] and dominio["chamadas"] == 0


def test_cotacao_imutavel_falha_sem_retentar(banco, dominio, monkeypatch):
    banco.responder("GET", "api_jobs", 200, [_job()])
    monkeypatch.setattr(repo, "obter_pesquisa", lambda pid: {"id": pid, "estado": "applied"})
    assert _processar(banco, _token(time.time() + 3600)) == "failed"
    assert _patches(banco)[-1]["erro_codigo"] == "IMMUTABLE"


def test_banco_fora_vira_erro_transitorio(banco, dominio):
    banco.responder("GET", "api_jobs", 200, [_job()])
    dominio["erro"] = db.ErroBanco("conexão")
    with pytest.raises(coleta.ErroTransitorio):
        _processar(banco, _token(time.time() + 3600))


def test_token_nao_vai_para_o_log_da_fila():
    from govconect_api.fila import FilaCelery

    enviados = []

    class AppFalso:
        def send_task(self, nome, **kw):
            enviados.append((nome, kw))

    token = _token(time.time() + 1800)
    FilaCelery(AppFalso()).enfileirar(job_id=JOB, token=token, tenant_id=TENANT_A,
                                      auth_user_id=USUARIO_A, secretaria_id=None)
    (nome, kw), = enviados
    assert kw["args"][1] == token                       # vai na mensagem...
    assert token not in kw["argsrepr"]                  # ...mas não no log
    assert 1700 <= kw["expires"] <= 1800                # e expira com ele


# ---------------------------------------------------------------------------
# Busca de UM item (M10b): o painel "Pesquisar preços" do GovDocs
# ---------------------------------------------------------------------------
ITEM = "dddddddd-0000-4000-8000-0000000000a1"


def _banco_do_item(estado="in_review", existe=True):
    b = PostgrestFalso()
    b.responder("GET", "pesquisas_preco", 200, [{"id": P, "auth_user_id": USUARIO_A, "estado": "review"}])
    b.responder("GET", "pesquisa_preco_itens", 200, [{"id": ITEM, "estado": estado}] if existe else [])
    return b


def test_pedido_de_um_item_grava_termo_e_filtros_e_total_1(emissor):
    banco = _banco_do_item()
    banco.responder("POST", "api_jobs", 201, [_job(total=1)])
    fila = FilaFalsa()
    r = _api(emissor, banco, fila).post(URL, headers=_h(emissor), json={
        "modo": "automatico", "item_id": ITEM, "termo": " caneta azul ",
        "filtros": {"janela_dias": 90, "uf": "pa"}})
    assert r.status_code == 202, r.text
    gravado = banco.corpo(next(c for c in banco.chamadas if c.method == "POST"))
    assert gravado["total"] == 1
    assert gravado["parametros"] == {"modo": "automatico", "item_id": ITEM, "termo": "caneta azul",
                                     "filtros": {"janela_dias": 90, "uf": "pa"}}


@pytest.mark.parametrize("estado, existe, status", [("complete", True, 409), ("in_review", False, 404)])
def test_item_concluido_ou_de_fora_nao_vai_para_a_fila(emissor, estado, existe, status):
    banco = _banco_do_item(estado, existe)
    fila = FilaFalsa()
    r = _api(emissor, banco, fila).post(URL, headers=_h(emissor), json={"item_id": ITEM})
    assert r.status_code == status
    assert fila.avisos == [] and not any(c.method == "POST" for c in banco.chamadas)


@pytest.mark.parametrize("filtros", [{"janela_dias": 10}, {"janela_dias": 400}, {"uf": "PAR"}, {"x": 1}])
def test_filtros_fora_da_regra_sao_422(emissor, filtros):
    banco = _banco_do_item()
    r = _api(emissor, banco, FilaFalsa()).post(URL, headers=_h(emissor), json={"item_id": ITEM, "filtros": filtros})
    assert r.status_code == 422


def test_worker_busca_so_o_item_pedido_literal_e_guarda_a_mensagem(banco, dominio, monkeypatch):
    recebido = {}

    def pesquisar_item(ctx, pesquisa_id, item_id, *, modo, termo, filtros, **opcoes):
        recebido.update(item=item_id, modo=modo, termo=termo, filtros=filtros, opcoes=opcoes)
        return type("R", (), {"mensagem": "Preço formado com 3 preços."})()

    monkeypatch.setattr(cotacoes, "pesquisar_item", pesquisar_item)
    banco.responder("GET", "api_jobs", 200, [_job(total=1, parametros={
        "modo": "manual", "item_id": ITEM, "termo": "caneta", "filtros": {"janela_dias": 90, "uf": "pa"}})])
    assert _processar(banco, _token(time.time() + 3600), fontes=[]) == "succeeded"
    assert recebido == {"item": ITEM, "modo": "manual", "termo": "caneta",
                        "filtros": {"janela_dias": 90, "uf": "PA", "literal": True}, "opcoes": {"fontes": []}}
    assert dominio["chamadas"] == 0, "o lote não pode rodar junto"
    final = _patches(banco)[-1]
    assert final["estado"] == "succeeded" and final["feitos"] == 1
    assert final["resultado"] == {"mensagem": "Preço formado com 3 preços."}
