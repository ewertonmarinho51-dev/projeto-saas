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
    estado = {"restantes": [2, 1, 0], "chamadas": 0, "erro": None, "vistos": [],
              "desfechos": ["pronto_para_revisao", "revisar_cv", "amostra_insuficiente"]}

    estado["recorte"] = ["i1", "i2", "i3"]
    estado["falhas_por_item"] = {}

    def passo(ctx, pesquisa_id, *, modo, tamanho, ja_tentados, item_ids=None, **opcoes):
        estado["chamadas"] += 1
        estado["opcoes"] = opcoes
        estado["item_ids"] = item_ids
        if estado.get("retentativa") is not None and item_ids != estado["recorte"]:
            # segunda passada: só os que falharam, um por vez
            pendentes = [i for i in item_ids if i not in ja_tentados]
            if not pendentes:
                return [], 0
            item = pendentes[0]
            ja_tentados.add(item)
            falhas = estado["falhas_por_item"].get(item, 0)
            estado["falhas_por_item"][item] = falhas - 1
            desfecho = "falha_tecnica" if falhas > 1 else "pronto_para_revisao"
            return ([type("R", (), {"item_id": item, "desfecho": desfecho})()],
                    len(pendentes) - 1)
        estado["vistos"].append(set(ja_tentados))
        if estado["erro"]:
            raise estado["erro"]
        item = f"i{estado['chamadas']}"
        ja_tentados.add(item)
        desfecho = estado["desfechos"][(estado["chamadas"] - 1) % 3]
        return ([type("R", (), {"item_id": item, "desfecho": desfecho})()],
                estado["restantes"].pop(0))

    monkeypatch.setattr(cotacoes, "pesquisar_em_lote", passo)
    monkeypatch.setattr(cotacoes, "recorte_do_lote",
                        lambda pesquisa_id, *, modo, **opcoes: list(estado["recorte"]))
    monkeypatch.setattr(repo, "obter_pesquisa", lambda pid: {"id": pid, "estado": "review"})
    return estado


def _processar(banco, token, **kw):
    kw.setdefault("dormir", lambda s: None)
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
    assert corpos[1]["parametros"]["item_ids"] == ["i1", "i2", "i3"] and corpos[1]["total"] == 3
    assert [c["feitos"] for c in corpos[2:5]] == [1, 2, 3]
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


@pytest.mark.parametrize("modo, total", [("automatico", 2), ("manual", 1)])
def test_total_do_lote_conta_o_buscado_a_mao_sem_cesta_so_na_automatica(emissor, banco, modo, total):
    # Produção, 09/11/2026: "Pesquisar" e depois "Cotação automática" na
    # pesquisa dava "0 de 0 itens" — o item buscado à mão fica em revisão.
    banco.respostas[("GET", "pesquisa_preco_itens")] = []
    # a busca manual pôs tudo como candidata: i2 ficou incompleto, cesta vazia
    banco.responder("GET", "pesquisa_preco_itens", 200, [
        {"id": "i1", "estado": "pending", "preco_estimado": None},
        {"id": "i2", "estado": "incomplete", "preco_estimado": None, "estatisticas": {"consideradas": 0}},
        {"id": "i3", "estado": "review", "preco_estimado": "4279.10", "estatisticas": {"consideradas": 14}},
        # a automática já rodou sobre i4 e não achou comparável: não refaz
        {"id": "i4", "estado": "incomplete", "preco_estimado": None, "estatisticas": {"consideradas": 0}},
    ])
    banco.responder("GET", "pesquisa_preco_eventos", 200, [
        {"item_id": "i4", "criado_em": "2026-11-09T19:43:00+00:00", "modo": "automatico"},
        {"item_id": "i2", "criado_em": "2026-11-09T12:35:00+00:00", "modo": "manual"},
        {"item_id": "i3", "criado_em": "2026-11-09T12:35:00+00:00", "modo": "manual"},
        {"item_id": "i4", "criado_em": "2026-11-09T12:35:00+00:00", "modo": "manual"},
    ])
    banco.responder("POST", "api_jobs", 201, [_job(total=total)])
    r = _api(emissor, banco, FilaFalsa()).post(URL, headers=_h(emissor), json={"modo": modo})
    assert r.status_code == 202, r.text
    assert banco.corpo(next(c for c in banco.chamadas if c.method == "POST"))["total"] == total


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


@pytest.mark.parametrize("modo, literal", [("manual", True), ("automatico", False)])
def test_o_modo_decide_a_ampliacao_da_busca_do_item(banco, dominio, monkeypatch, modo, literal):
    recebido = {}

    def pesquisar_item(ctx, pesquisa_id, item_id, *, modo, termo, filtros, **opcoes):
        recebido.update(filtros=filtros)
        return type("R", (), {"mensagem": ""})()

    monkeypatch.setattr(cotacoes, "pesquisar_item", pesquisar_item)
    banco.responder("GET", "api_jobs", 200, [_job(total=1, parametros={
        "modo": modo, "item_id": ITEM, "termo": "caneta",
        # pedido antigo com `literal` gravado não decide mais nada
        "filtros": {"janela_dias": 90, "uf": "", "literal": not literal}})])
    assert _processar(banco, _token(time.time() + 3600), fontes=[]) == "succeeded"
    assert recebido["filtros"]["literal"] is literal


def test_pedido_com_literal_e_recusado(emissor):
    r = _api(emissor, _banco_do_item(), FilaFalsa()).post(
        URL, headers=_h(emissor), json={"item_id": ITEM, "filtros": {"literal": True}})
    assert r.status_code == 422


def test_worker_busca_manual_e_do_termo_do_servidor_e_guarda_a_mensagem(banco, dominio, monkeypatch):
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


# ---------------------------------------------------------------------------
# Contratação conhecida do PNCP na busca de um item (10/11/2026)
# ---------------------------------------------------------------------------
CONTROLE_PNCP = "07954480000179-1-015836/2026"
LINK_PNCP = "https://pncp.gov.br/app/editais/07954480000179/2026/15836"


@pytest.mark.parametrize("entrada", [CONTROLE_PNCP, f"  {LINK_PNCP}  ",
                                      f"{LINK_PNCP}?x=http://169.254.169.254/"])
def test_contratacao_do_pncp_vai_para_a_fila_remontada_dos_digitos(emissor, entrada):
    banco = _banco_do_item()
    banco.responder("POST", "api_jobs", 201, [_job(total=1)])
    r = _api(emissor, banco, FilaFalsa()).post(URL, headers=_h(emissor), json={
        "modo": "manual", "item_id": ITEM, "contratacao_pncp": entrada})
    assert r.status_code == 202, r.text
    gravado = banco.corpo(next(c for c in banco.chamadas if c.method == "POST"))
    # nunca o texto digitado: o endereço montado com CNPJ, ano e sequencial
    assert gravado["parametros"]["contratacao_pncp"] == LINK_PNCP


@pytest.mark.parametrize("corpo", [
    {"item_id": ITEM, "contratacao_pncp": "caneta azul"},
    {"item_id": ITEM, "contratacao_pncp": "http://169.254.169.254/latest/meta-data"},
    {"contratacao_pncp": CONTROLE_PNCP},          # só na busca de UM item
])
def test_contratacao_do_pncp_invalida_ou_no_lote_e_422_sem_fila(emissor, corpo):
    banco = _banco_do_item()
    fila = FilaFalsa()
    r = _api(emissor, banco, fila).post(URL, headers=_h(emissor), json=corpo)
    assert r.status_code == 422 and r.json()["code"] == "PNCP_CONTRACT_INVALID"
    assert fila.avisos == [] and not any(c.method == "POST" for c in banco.chamadas)


def test_worker_soma_a_contratacao_do_pncp_as_fontes_de_sempre(banco, dominio, monkeypatch):
    recebido = {}

    def pesquisar_item(ctx, pesquisa_id, item_id, *, modo, termo, filtros, **opcoes):
        recebido.update(opcoes)
        return type("R", (), {"mensagem": "ok"})()

    monkeypatch.setattr(cotacoes, "pesquisar_item", pesquisar_item)
    monkeypatch.setattr(coleta, "_fonte_da_contratacao", lambda entrada: ("pncp", entrada))
    banco.responder("GET", "api_jobs", 200, [_job(total=1, parametros={
        "modo": "automatico", "item_id": ITEM, "termo": "", "filtros": {},
        "contratacao_pncp": LINK_PNCP})])
    assert _processar(banco, _token(time.time() + 3600), fontes=["compras"]) == "succeeded"
    assert recebido["fontes"] == ["compras", ("pncp", LINK_PNCP)]


def test_contratacao_canonica_le_so_digitos():
    assert coleta.contratacao_canonica(CONTROLE_PNCP) == LINK_PNCP
    assert coleta.contratacao_canonica("abc") is None
    fonte = coleta._fonte_da_contratacao(LINK_PNCP)
    assert fonte._controle == ("07954480000179", "2026", "15836")


# ---------------------------------------------------------------------------
# Lote: recorte fixo, desfecho por item, retomada e "Reprocessar pendentes"
# ---------------------------------------------------------------------------
def test_lote_grava_o_desfecho_de_cada_item_e_o_resumo(banco, dominio):
    banco.responder("GET", "api_jobs", 200, [_job(parametros={
        "modo": "automatico", "item_ids": ["i1", "i2", "i3"]})])
    assert _processar(banco, _token(time.time() + 3600), fontes=[]) == "succeeded"
    final = _patches(banco)[-1]["resultado"]
    assert final["itens"] == {"i1": "pronto_para_revisao", "i2": "revisar_cv",
                              "i3": "amostra_insuficiente"}
    assert final["resumo"] == {"pronto_para_revisao": 1, "revisar_cv": 1,
                               "amostra_insuficiente": 1}
    # cada item contado uma vez: processados = soma do resumo = total do recorte
    assert final["processados"] == sum(final["resumo"].values()) == 3
    assert final["pendentes"] == 2
    assert dominio["item_ids"] == ["i1", "i2", "i3"]


def test_reentrega_retoma_sem_refazer_o_que_tem_desfecho(banco, dominio):
    dominio["restantes"] = [0]
    banco.responder("GET", "api_jobs", 200, [_job(estado="running", feitos=2, parametros={
        "modo": "automatico", "item_ids": ["a", "b", "i1"]},
        resultado={"itens": {"a": "pronto_para_revisao", "b": "amostra_insuficiente",
                             "x": "<script>"}})])
    assert _processar(banco, _token(time.time() + 3600), fontes=[]) == "succeeded"
    # o que já tinha desfecho chega ao domínio como já tentado
    assert {"a", "b"} <= dominio["vistos"][0] and "x" not in dominio["vistos"][0]
    final = _patches(banco)[-1]["resultado"]
    assert final["itens"] == {"a": "pronto_para_revisao", "b": "amostra_insuficiente",
                              "i1": "pronto_para_revisao"}
    assert final["processados"] == 3


def test_item_do_recorte_resolvido_no_meio_conta_uma_vez(banco, dominio):
    dominio["restantes"] = [0]
    banco.responder("GET", "api_jobs", 200, [_job(parametros={
        "modo": "automatico", "item_ids": ["i1", "aceito"]})])
    assert _processar(banco, _token(time.time() + 3600), fontes=[]) == "succeeded"
    final = _patches(banco)[-1]["resultado"]
    assert final["itens"]["aceito"] == coleta.JA_RESOLVIDO
    assert final["processados"] == 2 and final["pendentes"] == 0


def test_recorte_fixado_na_largada_pelo_criterio_do_dominio(banco, dominio):
    dominio["recorte"] = ["a", "b"]
    dominio["restantes"] = [1, 0]
    banco.responder("GET", "api_jobs", 200, [_job(parametros={"modo": "automatico"})])
    assert _processar(banco, _token(time.time() + 3600), fontes=[]) == "succeeded"
    fixado = _patches(banco)[1]
    assert fixado["parametros"] == {"modo": "automatico", "item_ids": ["a", "b"]}
    assert fixado["total"] == 2 and dominio["item_ids"] == ["a", "b"]


def test_falha_transitoria_e_retentada_com_limite_e_espera(banco, dominio):
    # i3 falha (desfecho falha_tecnica na 1ª passada); depois falha mais uma
    # vez e na terceira tentativa responde
    dominio["retentativa"] = True
    dominio["desfechos"] = ["pronto_para_revisao", "revisar_cv", "falha_tecnica"]
    dominio["falhas_por_item"] = {"i3": 2}
    esperas = []
    banco.responder("GET", "api_jobs", 200, [_job(parametros={
        "modo": "automatico", "item_ids": ["i1", "i2", "i3"]})])
    assert _processar(banco, _token(time.time() + 3600), fontes=[],
                      dormir=esperas.append) == "succeeded"
    final = _patches(banco)[-1]["resultado"]
    assert final["itens"]["i3"] == "pronto_para_revisao"
    assert final["tentativas"]["i3"] == coleta.TENTATIVAS_POR_ITEM
    assert esperas == list(coleta.ESPERA_ENTRE_TENTATIVAS_S)


def test_falha_que_persiste_para_no_limite(banco, dominio):
    dominio["retentativa"] = True
    dominio["desfechos"] = ["pronto_para_revisao", "revisar_cv", "falha_tecnica"]
    dominio["falhas_por_item"] = {"i3": 99}
    banco.responder("GET", "api_jobs", 200, [_job(parametros={
        "modo": "automatico", "item_ids": ["i1", "i2", "i3"]})])
    assert _processar(banco, _token(time.time() + 3600), fontes=[]) == "succeeded"
    final = _patches(banco)[-1]["resultado"]
    assert final["itens"]["i3"] == "falha_tecnica"
    assert final["tentativas"]["i3"] == coleta.TENTATIVAS_POR_ITEM


def test_resumo_exibivel_so_com_motivos_conhecidos():
    exibido = coleta._resultado_exibivel({  # noqa: SLF001
        "resumo": {"revisar_cv": 2, "inventado": 9, "falha_tecnica": True,
                   "pronto_para_revisao": -1},
        "processados": 2, "pendentes": 2, "itens": {"i1": "revisar_cv"}})
    assert exibido == {"resumo": {"revisar_cv": 2}, "processados": 2, "pendentes": 2}


def test_pedido_de_lote_nao_fixa_recorte_nem_aceita_reprocessar(emissor, banco):
    banco.respostas[("GET", "pesquisa_preco_itens")] = []
    banco.responder("GET", "pesquisa_preco_itens", 200, [
        {"id": "i1", "estado": "pending", "preco_estimado": None}])
    banco.responder("GET", "pesquisa_preco_eventos", 200, [])
    banco.responder("POST", "api_jobs", 201, [_job(total=1)])
    api = _api(emissor, banco, FilaFalsa())
    assert api.post(URL, headers=_h(emissor),
                    json={"modo": "automatico", "reprocessar": True}).status_code == 422
    r = api.post(URL, headers=_h(emissor), json={"modo": "automatico"})
    assert r.status_code == 202, r.text
    corpo = banco.corpo(next(c for c in banco.chamadas if c.method == "POST"))
    assert corpo["parametros"] == {"modo": "automatico"} and corpo["total"] == 1


def test_reentrega_nao_retenta_alem_do_limite(banco, dominio):
    # job retomado: i3 já gastou as tentativas desta execução
    dominio["retentativa"] = True
    dominio["restantes"] = [0]
    esperas = []
    banco.responder("GET", "api_jobs", 200, [_job(estado="running", parametros={
        "modo": "automatico", "item_ids": ["i1", "i2", "i3"]},
        resultado={"itens": {"i1": "pronto_para_revisao", "i2": "revisar_cv",
                             "i3": "falha_tecnica"},
                   "tentativas": {"i1": 1, "i2": 1, "i3": coleta.TENTATIVAS_POR_ITEM}})])
    assert _processar(banco, _token(time.time() + 3600), fontes=[],
                      dormir=esperas.append) == "succeeded"
    assert esperas == [] and _patches(banco)[-1]["resultado"]["itens"]["i3"] == "falha_tecnica"



# ---------------------------------------------------------------------------
# JEV no fluxo web (13/11/2026): o seletor chega à cotação automática
# ---------------------------------------------------------------------------
def test_worker_passa_o_seletor_do_jev_ao_item_automatico(banco, dominio, monkeypatch):
    from src import governanca
    from src.precos import seletor as seletor_mod

    marca = object()
    monkeypatch.setattr(coleta.db, "flag_ativa", lambda nome: nome == governanca.FLAG_JEV_PRECOS)
    monkeypatch.setattr(seletor_mod, "seletor_padrao", lambda: marca)
    recebido = {}

    def pesquisar_item(ctx, pesquisa_id, item_id, *, modo, termo, filtros, **opcoes):
        recebido.update(opcoes)
        return type("R", (), {"mensagem": "ok"})()

    monkeypatch.setattr(cotacoes, "pesquisar_item", pesquisar_item)
    banco.responder("GET", "api_jobs", 200, [_job(total=1, parametros={
        "modo": "automatico", "item_id": ITEM, "termo": "", "filtros": {}})])
    assert _processar(banco, _token(time.time() + 3600), fontes=[]) == "succeeded"
    assert recebido["seletor"] is marca


def test_worker_passa_o_seletor_do_jev_ao_lote(banco, dominio, monkeypatch):
    from src import governanca
    from src.precos import seletor as seletor_mod

    marca = object()
    monkeypatch.setattr(coleta.db, "flag_ativa", lambda nome: nome == governanca.FLAG_JEV_PRECOS)
    monkeypatch.setattr(seletor_mod, "seletor_padrao", lambda: marca)
    banco.responder("GET", "api_jobs", 200, [_job()])
    assert _processar(banco, _token(time.time() + 3600), fontes=[]) == "succeeded"
    assert dominio["opcoes"]["seletor"] is marca


def test_flag_do_jev_ilegivel_nao_liga_o_seletor(banco, dominio, monkeypatch):
    def quebrada(nome):
        raise RuntimeError("banco fora")

    monkeypatch.setattr(coleta.db, "flag_ativa", quebrada)
    banco.responder("GET", "api_jobs", 200, [_job()])
    assert _processar(banco, _token(time.time() + 3600), fontes=[]) == "succeeded"
    assert "seletor" not in dominio["opcoes"]
