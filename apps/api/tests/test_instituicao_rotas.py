"""
Cadastro institucional (M7a): o que a API exige e devolve. As funções do
domínio (`db.*`) são substituídas por um cadastro em memória — o que o
banco FAZ (RLS `e_admin()` da 0025) é prova da pilha real.
"""

import base64
import datetime as dt

import pytest
from fastapi.testclient import TestClient

from govconect_api.config import carregar
from govconect_api.main import criar_app
from govconect_api.verificador import VerificadorSupabase
from src import db

from apoio_jwt import EMISSOR, Emissor, PostgrestFalso

SEC = "dddddddd-0000-4000-8000-000000000001"
SRV = "eeeeeeee-0000-4000-8000-000000000001"
POR = "ffffffff-0000-4000-8000-000000000001"
PNG = base64.b64encode(b"\x89PNG\r\n\x1a\nconteudo").decode()


@pytest.fixture
def cadastro(monkeypatch):
    estado = {
        "flags": {"multi_prefeituras": True, "price_research": True, "demand_consolidation": False},
        "config": {},
        "secretarias": [{"id": SEC, "nome": "Secretaria de Educação", "padrao": True,
                         "cabecalho_img": PNG, "cabecalho": "", "rodape": ""}],
        "servidores": [{"id": SRV, "nome": "Ana Souza", "cargo": "Agente", "matricula": "12",
                        "email": None, "ativo": True}],
        "portarias": [],
        "membros": {},
        "tenant_modulos": {"price_research": True},
        "secretaria_modulos": {},
        "gravacoes": [],
    }
    monkeypatch.setattr(db, "flag_ativa", lambda nome: estado["flags"].get(nome, False))
    monkeypatch.setattr(db, "obter_config", lambda chave: estado["config"].get(chave, ""))
    monkeypatch.setattr(db, "listar_secretarias", lambda incluir_inativas=False: estado["secretarias"])
    monkeypatch.setattr(db, "listar_servidores", lambda incluir_inativos=False: [
        s for s in estado["servidores"] if incluir_inativos or s["ativo"]])

    def salvar_servidor(registro, servidor_id=None):
        estado["gravacoes"].append(("servidor", servidor_id, registro))
        if servidor_id:
            return servidor_id
        novo = {"id": "eeeeeeee-0000-4000-8000-000000000002", "ativo": True, **registro}
        estado["servidores"].append(novo)
        return novo["id"]
    monkeypatch.setattr(db, "salvar_servidor", salvar_servidor)

    monkeypatch.setattr(db, "listar_portarias", lambda secretaria_id=None, tipo=None: estado["portarias"])

    def salvar_portaria(registro, portaria_id=None):
        estado["gravacoes"].append(("portaria", portaria_id, registro))
        return portaria_id or POR
    monkeypatch.setattr(db, "salvar_portaria", salvar_portaria)
    monkeypatch.setattr(db, "listar_membros_de_portaria", lambda pid: estado["membros"].get(pid, []))

    def salvar_membro(pid, sid, funcao, ordem=100):
        estado["gravacoes"].append(("membro", pid, {"servidor_id": sid, "funcao": funcao, "ordem": ordem}))
        estado["membros"].setdefault(pid, []).append({"nome": "Ana Souza", "funcao": funcao})
    monkeypatch.setattr(db, "salvar_membro_de_portaria", salvar_membro)
    monkeypatch.setattr(db, "modulos_do_tenant", lambda: estado["tenant_modulos"])
    monkeypatch.setattr(db, "modulos_da_secretaria", lambda sid: estado["secretaria_modulos"])

    def salvar_modulo_do_tenant(modulo, habilitado):
        estado["gravacoes"].append(("tenant_modulo", modulo, habilitado))
    monkeypatch.setattr(db, "salvar_modulo_do_tenant", salvar_modulo_do_tenant)

    def salvar_modulo_da_secretaria(sid, modulo, valor):
        if valor == "HABILITADO" and not estado["tenant_modulos"].get(modulo):
            raise db.ErroBanco("A Prefeitura não habilitou este módulo.")
        estado["gravacoes"].append(("secretaria_modulo", modulo, valor))
    monkeypatch.setattr(db, "salvar_modulo_da_secretaria", salvar_modulo_da_secretaria)
    return estado


@pytest.fixture
def emissor():
    return Emissor()


@pytest.fixture
def api(emissor, cadastro):
    config = carregar({"APP_ENV": "test", "SUPABASE_URL": "https://exemplo-staging.supabase.co",
                       "SUPABASE_KEY": "chave-publicavel-de-teste"})
    rest = PostgrestFalso().cliente()
    verificador = VerificadorSupabase(emissor=EMISSOR, rest=rest, chave_para=emissor.chave_para)
    return TestClient(criar_app(config, verificador=verificador, rest=rest), raise_server_exceptions=False)


def _admin(emissor):
    return {"Authorization": f"Bearer {emissor.token(papel='admin')}"}


def test_usuario_comum_nao_entra(api, emissor):
    r = api.get("/api/v1/admin/instituicao", headers={"Authorization": f"Bearer {emissor.token()}"})
    assert r.status_code == 403


def test_flag_do_cadastro_desligada_e_404(api, emissor, cadastro):
    cadastro["flags"]["multi_prefeituras"] = False
    assert api.get("/api/v1/admin/instituicao", headers=_admin(emissor)).status_code == 404


def test_visao_lista_secoes_secretarias_e_vocabulario(api, emissor, cadastro):
    corpo = api.get("/api/v1/admin/instituicao", headers=_admin(emissor)).json()
    assert corpo["secoes"] == ["Timbrado", "Módulos", "Servidores", "Portarias"]
    assert corpo["secretarias"] == [{"id": SEC, "nome": "Secretaria de Educação"}]
    assert {o["codigo"] for o in corpo["tipos_de_portaria"]} >= {"EQUIPE_PLANEJAMENTO", "PREGOEIRO"}
    # Seção desligada de propósito some (ausente = ligada).
    cadastro["config"]["flag_portarias"] = "0"
    assert "Portarias" not in api.get("/api/v1/admin/instituicao", headers=_admin(emissor)).json()["secoes"]
    assert api.get(f"/api/v1/admin/instituicao/portarias?secretaria_id={SEC}",
                   headers=_admin(emissor)).status_code == 404


def test_cadastrar_e_desativar_servidor(api, emissor, cadastro):
    r = api.post("/api/v1/admin/instituicao/servidores", headers=_admin(emissor),
                 json={"nome": "  Carlos Lima ", "cargo": "Pregoeiro", "matricula": "", "email": None})
    assert r.status_code == 201 and r.json()["nome"] == "Carlos Lima" and r.json()["matricula"] is None
    r = api.patch(f"/api/v1/admin/instituicao/servidores/{SRV}", headers=_admin(emissor), json={"ativo": False})
    assert r.status_code == 200 and r.json()["ativo"] is False
    assert ("servidor", SRV, {"ativo": False}) in cadastro["gravacoes"]


@pytest.mark.parametrize("corpo", [{"nome": ""}, {"nome": "x", "tenant_id": "outro"}, {"nome": "x" * 201}])
def test_servidor_invalido_e_422(api, emissor, corpo):
    assert api.post("/api/v1/admin/instituicao/servidores", headers=_admin(emissor), json=corpo).status_code == 422


def test_servidor_de_outro_municipio_e_404(api, emissor):
    r = api.patch("/api/v1/admin/instituicao/servidores/eeeeeeee-0000-4000-8000-0000000000ff",
                  headers=_admin(emissor), json={"ativo": False})
    assert r.status_code == 404


def test_portaria_nasce_rascunho_e_ativa_depois(api, emissor, cadastro):
    hoje = dt.date.today().isoformat()
    r = api.post("/api/v1/admin/instituicao/portarias", headers=_admin(emissor), json={
        "secretaria_id": SEC, "tipo": "EQUIPE_PLANEJAMENTO", "numero": "003", "ano": 2026,
        "data_inicio_vigencia": hoje})
    assert r.status_code == 201, r.text
    assert r.json()["situacao_declarada"] == "RASCUNHO"
    cadastro["portarias"].append({"id": POR, "secretaria_id": SEC, "tipo": "EQUIPE_PLANEJAMENTO",
                                  "numero": "003", "ano": 2026, "status": "RASCUNHO",
                                  "data_inicio_vigencia": hoje})
    r = api.patch(f"/api/v1/admin/instituicao/portarias/{POR}", headers=_admin(emissor), json={"status": "ATIVA"})
    assert r.status_code == 200 and r.json()["situacao_declarada"] == "ATIVA"
    r = api.post(f"/api/v1/admin/instituicao/portarias/{POR}/membros", headers=_admin(emissor),
                 json={"servidor_id": SRV, "funcao": "EQUIPE_PLANEJAMENTO"})
    assert r.status_code == 201 and r.json()["membros"][0]["nome"] == "Ana Souza"


def test_portaria_com_vigencia_invertida_ou_tipo_inventado_e_422(api, emissor):
    base = {"secretaria_id": SEC, "numero": "1", "ano": 2026, "data_inicio_vigencia": "2026-05-01"}
    assert api.post("/api/v1/admin/instituicao/portarias", headers=_admin(emissor),
                    json={**base, "tipo": "INVENTADO"}).status_code == 422
    assert api.post("/api/v1/admin/instituicao/portarias", headers=_admin(emissor),
                    json={**base, "tipo": "FISCAL", "data_fim_vigencia": "2026-01-01"}).status_code == 422


def test_membro_so_de_servidor_cadastrado_e_funcao_valida(api, emissor, cadastro):
    cadastro["portarias"].append({"id": POR, "secretaria_id": SEC, "tipo": "EQUIPE_PLANEJAMENTO",
                                  "numero": "3", "ano": 2026, "status": "ATIVA"})
    assert api.post(f"/api/v1/admin/instituicao/portarias/{POR}/membros", headers=_admin(emissor),
                    json={"servidor_id": "eeeeeeee-0000-4000-8000-0000000000ff",
                          "funcao": "EQUIPE_PLANEJAMENTO"}).status_code == 422
    assert api.post(f"/api/v1/admin/instituicao/portarias/{POR}/membros", headers=_admin(emissor),
                    json={"servidor_id": SRV, "funcao": "PREFEITO"}).status_code == 422


def test_modulos_e_a_recusa_do_dominio(api, emissor, cadastro):
    corpo = api.get(f"/api/v1/admin/instituicao/modulos?secretaria_id={SEC}", headers=_admin(emissor)).json()
    preco = next(m for m in corpo["modulos"] if m["modulo"] == "price_research")
    assert preco["disponivel_no_sistema"] and preco["na_prefeitura"] and preco["na_secretaria"] == "HERDAR"
    # Desligado no sistema: não se liga na prefeitura.
    r = api.put("/api/v1/admin/instituicao/modulos/prefeitura/demand_consolidation", headers=_admin(emissor),
                json={"habilitado": True})
    assert r.status_code == 409
    # A prefeitura não habilitou: a secretaria não pode abrir (mensagem do domínio).
    cadastro["flags"]["canonical_facts"] = True
    r = api.put(f"/api/v1/admin/instituicao/modulos/secretarias/{SEC}/canonical_facts", headers=_admin(emissor),
                json={"estado": "HABILITADO"})
    assert r.status_code == 422 and "não habilitou" in r.json()["message"]
    assert api.put("/api/v1/admin/instituicao/modulos/prefeitura/modulo_inventado", headers=_admin(emissor),
                   json={"habilitado": True}).status_code == 404


def test_timbrado_mostra_a_decisao_da_exportacao(api, emissor):
    corpo = api.get(f"/api/v1/admin/instituicao/timbrado?secretaria_id={SEC}", headers=_admin(emissor)).json()
    assert corpo["origem"] == "secretaria"
    assert corpo["cabecalho_img"].startswith("data:image/png;base64,")
