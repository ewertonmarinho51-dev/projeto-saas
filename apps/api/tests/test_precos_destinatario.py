"""
O destinatário do relatório pela API (0041): criar com ele, trocar, ler, listar
os órgãos do município — e o worker de emissão tirar o timbrado DELE.

PostgREST simulado; o domínio de validação (`cotacoes.destinatario_validado`)
é o verdadeiro, só o repositório é substituído.
"""

import pytest
from fastapi.testclient import TestClient

from govconect_api import relatorios
from govconect_api.config import carregar
from govconect_api.main import criar_app
from govconect_api.verificador import VerificadorSupabase
from src import db
from src.precos import emissao
from src.precos import repositorio as repo

from apoio_jwt import EMISSOR, SECRETARIA_A, USUARIO_A, Emissor, PostgrestFalso

P = "eeeeeeee-0000-4000-8000-000000000001"
PREFEITURA = "bbbbbbbb-0000-4000-8000-000000000001"
DE_OUTRO = "99999999-0000-4000-8000-000000000009"
SECRETARIAS = [{"id": PREFEITURA, "nome": "Prefeitura Municipal de Paragominas", "padrao": True},
               {"id": SECRETARIA_A, "nome": "Secretaria de Administração", "padrao": False}]


@pytest.fixture
def emissor():
    return Emissor()


def _api(emissor, banco):
    config = carregar({"APP_ENV": "test", "SUPABASE_URL": "https://exemplo-staging.supabase.co",
                       "SUPABASE_KEY": "chave-publicavel-de-teste", "PRICE_RESEARCH_ENABLED": "1"})
    rest = banco.cliente()
    return TestClient(criar_app(config, rest=rest, verificador=VerificadorSupabase(
        emissor=EMISSOR, rest=rest, chave_para=emissor.chave_para)), raise_server_exceptions=False)


def _h(emissor, **extra):
    return {"Authorization": f"Bearer {emissor.token()}", **extra}


def _dono(dono=USUARIO_A):
    b = PostgrestFalso()
    b.responder("GET", "pesquisas_preco", 200, [{"id": P, "auth_user_id": dono, "estado": "applied"}])
    return b


@pytest.fixture
def dominio(monkeypatch):
    estado = {"gravado": None, "criada": None}
    monkeypatch.setattr(db, "listar_secretarias", lambda incluir_inativas=False: list(SECRETARIAS))
    monkeypatch.setattr(repo, "obter_pesquisa", lambda pid: {"id": pid, "estado": "applied"})
    monkeypatch.setattr(repo, "obter_por_chave", lambda chave: None)
    monkeypatch.setattr(repo, "registrar_evento", lambda *a, **k: None)

    def atualizar(pid, **campos):
        estado["gravado"] = campos
        return {"id": pid, **campos}

    def criar(nome, **k):
        estado["criada"] = k
        return {"id": P, "nome": nome, "estado": "draft"}

    monkeypatch.setattr(repo, "atualizar_pesquisa", atualizar)
    monkeypatch.setattr(repo, "criar_pesquisa", criar)
    return estado


# ---------------------------------------------------------------------------
# Criar
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("corpo, secretaria, externo", [
    ({"destinatario_secretaria_id": PREFEITURA}, PREFEITURA, ""),
    ({"destinatario_externo": " Prefeitura  de Ulianópolis "}, None, "Prefeitura de Ulianópolis"),
    ({}, None, ""),
])
def test_criar_grava_o_destinatario(emissor, dominio, corpo, secretaria, externo):
    r = _api(emissor, PostgrestFalso()).post(
        "/api/v1/precos/pesquisas", headers=_h(emissor, **{"Idempotency-Key": "nova-dest-01"}),
        json={"nome": "Material", **corpo})
    assert r.status_code == 201, r.text
    assert dominio["criada"]["destinatario_secretaria_id"] == secretaria
    assert dominio["criada"]["destinatario_externo"] == externo


@pytest.mark.parametrize("corpo, codigo", [
    ({"destinatario_secretaria_id": PREFEITURA, "destinatario_externo": "Outra"}, 422),
    ({"destinatario_secretaria_id": DE_OUTRO}, 422),
    ({"destinatario_externo": "x" * 201}, 422),
    ({"destinatario_secretaria_id": "nao-e-uuid"}, 422),
])
def test_criar_recusa_destinatario_invalido(emissor, dominio, corpo, codigo):
    r = _api(emissor, PostgrestFalso()).post(
        "/api/v1/precos/pesquisas", headers=_h(emissor, **{"Idempotency-Key": "nova-dest-02"}),
        json={"nome": "Material", **corpo})
    assert r.status_code == codigo, r.text
    assert dominio["criada"] is None


# ---------------------------------------------------------------------------
# Trocar
# ---------------------------------------------------------------------------
URL = f"/api/v1/precos/pesquisas/{P}/destinatario"


def test_trocar_para_outro_orgao_vale_ate_em_cotacao_aplicada(emissor, dominio):
    r = _api(emissor, _dono()).put(URL, headers=_h(emissor), json={"externo": "Prefeitura de Dom Eliseu"})
    assert r.status_code == 200, r.text
    assert r.json() == {"tipo": "externo", "secretaria_id": None, "nome": "Prefeitura de Dom Eliseu"}
    assert dominio["gravado"] == {"destinatario_secretaria_id": None,
                                  "destinatario_externo": "Prefeitura de Dom Eliseu"}


def test_trocar_para_secretaria_do_municipio(emissor, dominio):
    r = _api(emissor, _dono()).put(URL, headers=_h(emissor), json={"secretaria_id": SECRETARIA_A})
    assert r.status_code == 200, r.text
    assert r.json()["tipo"] == "secretaria" and r.json()["secretaria_id"] == SECRETARIA_A


def test_voltar_a_nao_informado(emissor, dominio):
    r = _api(emissor, _dono()).put(URL, headers=_h(emissor), json={})
    assert r.status_code == 200 and r.json()["tipo"] == "nenhum"


def test_secretaria_de_outro_municipio_e_recusada(emissor, dominio):
    r = _api(emissor, _dono()).put(URL, headers=_h(emissor), json={"secretaria_id": DE_OUTRO})
    assert r.status_code == 422 and "município" in r.json()["message"]
    assert dominio["gravado"] is None


def test_so_o_dono_ou_admin_troca(emissor, dominio):
    r = _api(emissor, _dono(dono="00000000-0000-4000-8000-0000000000ff")).put(
        URL, headers=_h(emissor), json={"externo": "Outra"})
    assert r.status_code == 403 and dominio["gravado"] is None


def test_identidade_nao_entra_pelo_corpo(emissor, dominio):
    r = _api(emissor, _dono()).put(URL, headers=_h(emissor), json={"externo": "X", "tenant_id": "t"})
    assert r.status_code == 422 and dominio["gravado"] is None


# ---------------------------------------------------------------------------
# Ler e listar
# ---------------------------------------------------------------------------
def test_leitura_traz_o_destinatario(emissor):
    banco = PostgrestFalso()
    banco.responder("GET", "pesquisas_preco", 200, [{
        "id": P, "nome": "N", "objeto": "", "estado": "draft", "valor_global": None,
        "data_base": None, "responsavel": "", "local_referencia": "", "processo_id": None,
        "versao": 1, "criado_em": "", "atualizado_em": "",
        "destinatario_secretaria_id": None, "destinatario_externo": "Prefeitura X"}])
    banco.responder("GET", "pesquisa_preco_itens", 200, [])
    r = _api(emissor, banco).get(f"/api/v1/precos/pesquisas/{P}", headers=_h(emissor))
    assert r.status_code == 200, r.text
    assert r.json()["destinatario"] == {"tipo": "externo", "secretaria_id": None, "nome": "Prefeitura X"}
    select = banco.chamadas[-2].url.params["select"]
    assert "destinatario_secretaria_id" in select and "destinatario_externo" in select


def test_orgaos_do_municipio_sem_timbrado_na_resposta(emissor):
    banco = PostgrestFalso()
    banco.responder("GET", "secretarias", 200, [dict(s) for s in SECRETARIAS])
    r = _api(emissor, banco).get("/api/v1/precos/orgaos-destinatarios", headers=_h(emissor))
    assert r.status_code == 200, r.text
    assert r.json() == [
        {"id": PREFEITURA, "nome": "Prefeitura Municipal de Paragominas", "padrao": True, "vinculo": False},
        {"id": SECRETARIA_A, "nome": "Secretaria de Administração", "padrao": False, "vinculo": True}]
    pedido = banco.chamadas[-1]
    # O timbrado (base64, centenas de KB) não viaja para montar um seletor.
    assert pedido.url.params["select"] == "id,nome,padrao"
    assert pedido.url.params["ativo"] == "is.true"


# ---------------------------------------------------------------------------
# Worker de emissão: o timbrado vem do destinatário da pesquisa
# ---------------------------------------------------------------------------
def test_worker_pede_o_timbrado_do_destinatario(monkeypatch):
    from src.precos import ciencia

    pesquisa = {"id": P, "destinatario_externo": "Prefeitura de Ulianópolis"}
    pedidos, marcas = [], []
    banco = PostgrestFalso()
    banco.responder("GET", "api_jobs", 200, [{
        "id": "j1", "estado": "queued", "tipo": relatorios.TIPO_DO_JOB, "recurso_id": P,
        "parametros": {"tipo": "cotacao", "formato": "docx"}, "tentativas": 0}])
    monkeypatch.setattr(relatorios, "_flags", lambda: (True, True))
    monkeypatch.setattr(relatorios, "_carregar", lambda pid, t: (pesquisa, [{"id": "i1"}], {"i1": []}))
    monkeypatch.setattr(relatorios, "atualizar_job", lambda *a, **k: None)
    monkeypatch.setattr(emissao, "conferir_cestas", lambda *a: None)
    monkeypatch.setattr(ciencia, "exigir", lambda *a, **k: None)
    monkeypatch.setattr(ciencia, "para_documento", lambda *a: None)
    monkeypatch.setattr(emissao, "marca_resolvida", lambda: pytest.fail("não é o vínculo que decide"))
    real = emissao.marca_do_relatorio
    monkeypatch.setattr(emissao, "marca_do_relatorio",
                        lambda p: pedidos.append(p) or real(p))
    monkeypatch.setattr(emissao, "renderizar", lambda *a, **k: (
        marcas.append(k["marca"]) or (b"x", "r.docx", "x/x")))
    monkeypatch.setattr(emissao, "registrar", lambda *a, **k: ({"hash_decisorio": "h"}, True))

    class Deposito:
        def guardar(self, job_id, artefato):
            return 0

    estado = relatorios.processar_relatorio(
        job_id="j1", token="t", tenant_id="ten", auth_user_id=USUARIO_A, secretaria_id=None,
        usuario_id="u", rest=banco.cliente(), deposito=Deposito())
    assert estado == "succeeded"
    assert pedidos == [pesquisa] and marcas == [None]
