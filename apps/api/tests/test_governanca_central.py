"""
Centro de Governança em leitura (M8a): a regra de acesso do Streamlit
(flag `governance_center` + papel de governança; admin sem papel = admin
municipal), as abas pelas flags próprias e o papel lido SÓ do
`app_metadata` — vocabulário fechado, igual ao do domínio.
"""

import pytest
from fastapi.testclient import TestClient

from govconect_api import verificador
from govconect_api.config import carregar
from govconect_api.main import criar_app
from govconect_api.verificador import VerificadorSupabase
from src import catalogo, db, governanca

from apoio_jwt import EMISSOR, TENANT_A, Emissor, PostgrestFalso

BASE = "/api/v1/governanca"


@pytest.fixture
def emissor():
    return Emissor()


@pytest.fixture
def flags(monkeypatch):
    ligadas = {governanca.FLAG_CENTRO: True, governanca.FLAG_CATALOGO: True}
    monkeypatch.setattr(db, "flag_ativa", lambda nome: ligadas.get(nome, False))
    itens = {
        "clausula": [
            {"artefato": {"id": "a1", "chave_estavel": "clausula.tr.garantia", "tenant_id": "t"},
             "versoes": [{}, {}],
             "ultima": {"id": "v2", "versao": 2, "status": "DRAFT", "hash": "f" * 64,
                        "payload": {"titulo": "Garantia", "blocos": ["Texto"]}},
             "publicada": {"id": "v1", "versao": 1, "status": "PUBLISHED", "hash": "a" * 64, "payload": {}}},
            {"artefato": {"id": "a2", "chave_estavel": "clausula.dfd.objeto", "tenant_id": None},
             "versoes": [{}], "ultima": None, "publicada": None},
        ],
        "politica": [
            {"artefato": {"id": "p1", "chave_estavel": "politica.srp", "tenant_id": "t"}, "versoes": [{}],
             "ultima": {"id": "pv", "versao": 1, "status": "PUBLISHED", "hash": "b" * 64,
                        "payload": {"condicao": {"field": "procedimento.srp", "operator": "=", "value": True}}},
             "publicada": None},
        ],
    }
    monkeypatch.setattr(catalogo, "listar_com_situacao", lambda tipo="clausula": itens.get(tipo, []))
    return ligadas


def _api(emissor):
    config = carregar({"APP_ENV": "test", "SUPABASE_URL": "https://exemplo-staging.supabase.co",
                       "SUPABASE_KEY": "chave-publicavel-de-teste"})
    rest = PostgrestFalso().cliente()
    return TestClient(criar_app(config, rest=rest, verificador=VerificadorSupabase(
        emissor=EMISSOR, rest=rest, chave_para=emissor.chave_para)), raise_server_exceptions=False)


def _h(emissor, **claims):
    return {"Authorization": f"Bearer {emissor.token(**claims)}"}


def test_servidor_comum_nao_entra_e_admin_entra_como_admin_municipal(emissor, flags):
    api = _api(emissor)
    assert api.get(BASE, headers=_h(emissor)).status_code == 403
    r = api.get(BASE, headers=_h(emissor, papel="admin"))
    assert r.status_code == 200 and r.json()["papel"] == "admin_municipal"


def test_flag_do_centro_desligada_e_404(emissor, flags):
    flags[governanca.FLAG_CENTRO] = False
    assert _api(emissor).get(BASE, headers=_h(emissor, papel="admin")).status_code == 404


def test_resumo_e_abas_pelas_flags(emissor, flags):
    corpo = _api(emissor).get(BASE, headers=_h(emissor, papel="admin")).json()
    assert corpo["resumo"] == {"clausulas": 2, "publicadas": 1, "em_elaboracao": 1}
    assert {a["tipo"]: a["ativa"] for a in corpo["abas"]} == {
        "clausula": True, "politica": False, "familia": True, "template": True}


def test_artefatos_com_ultima_vigente_escopo_e_hash_curto(emissor, flags):
    r = _api(emissor).get(f"{BASE}/artefatos?tipo=clausula", headers=_h(emissor, papel="admin"))
    assert r.status_code == 200, r.text
    primeiro, segundo = r.json()
    assert primeiro["ultima"]["status_rotulo"] == "rascunho" and primeiro["vigente"]["versao"] == 1
    assert len(primeiro["ultima"]["hash"]) == 12 and primeiro["escopo"] == "municipio"
    assert segundo["ultima"] is None and segundo["escopo"] == "plataforma"


def test_aba_desligada_e_404_e_politica_vem_descrita(emissor, flags):
    api = _api(emissor)
    assert api.get(f"{BASE}/artefatos?tipo=politica", headers=_h(emissor, papel="admin")).status_code == 404
    flags[governanca.FLAG_POLITICAS_VISUAL] = True
    (politica,) = api.get(f"{BASE}/artefatos?tipo=politica", headers=_h(emissor, papel="admin")).json()
    assert politica["descricao"] == "procedimento.srp = True"


def test_tipo_fora_do_vocabulario_e_422(emissor, flags):
    assert _api(emissor).get(f"{BASE}/artefatos?tipo=processo", headers=_h(emissor, papel="admin")).status_code == 422


def test_me_diz_se_o_centro_esta_disponivel(emissor, flags):
    api = _api(emissor)
    assert api.get("/api/v1/me", headers=_h(emissor, papel="admin")).json()["governanca"] is True
    assert api.get("/api/v1/me", headers=_h(emissor)).json()["governanca"] is False
    flags[governanca.FLAG_CENTRO] = False
    assert api.get("/api/v1/me", headers=_h(emissor, papel="admin")).json()["governanca"] is False


def test_vocabulario_de_papeis_igual_ao_do_dominio():
    assert verificador.PAPEIS_GOVERNANCA == governanca.PAPEIS_GOVERNANCA


def _com_papel(emissor, papel_governanca):
    from apoio_jwt import SECRETARIA_A, TENANT_A

    return {"Authorization": "Bearer " + emissor.token(extra={"app_metadata": {
        "tenant_id": TENANT_A, "papel": "usuario", "secretaria_id": SECRETARIA_A,
        "papel_governanca": papel_governanca}})}


def test_papel_de_governanca_vem_do_app_metadata(emissor, flags):
    r = _api(emissor).get(BASE, headers=_com_papel(emissor, "auditor"))
    assert r.status_code == 200 and r.json()["papel"] == "auditor"


def test_papel_de_governanca_desconhecido_nao_vira_acesso(emissor, flags):
    assert _api(emissor).get(BASE, headers=_com_papel(emissor, "superusuario")).status_code == 403


# ---------------------------------------------------------------------------
# Escrita (M8b): só pelas RPCs da 0036
# ---------------------------------------------------------------------------
VERSAO = "aaaaaaaa-0000-4000-8000-000000000001"
CLAUSULA = {"titulo": "DA GARANTIA", "comportamento": "FIXED_PARAMETERIZED",
            "blocos": ["A garantia será de {{percentual}}% do valor."],
            "parametros_permitidos": ["percentual"], "parametros_obrigatorios": ["percentual"]}


def _api_com(emissor, banco):
    config = carregar({"APP_ENV": "test", "SUPABASE_URL": "https://exemplo-staging.supabase.co",
                       "SUPABASE_KEY": "chave-publicavel-de-teste"})
    rest = banco.cliente()
    return TestClient(criar_app(config, rest=rest, verificador=VerificadorSupabase(
        emissor=EMISSOR, rest=rest, chave_para=emissor.chave_para)), raise_server_exceptions=False)


def _rpcs(banco):
    return [c for c in banco.chamadas if "/rpc/" in c.url.path]


def test_criar_valida_o_contrato_antes_do_banco(emissor, flags):
    banco = PostgrestFalso()
    r = _api_com(emissor, banco).post(f"{BASE}/artefatos", headers=_h(emissor, papel="admin"), json={
        "tipo": "clausula", "chave": "clausula.tr.garantia", "payload": {"titulo": "sem o resto"}})
    assert r.status_code == 422 and _rpcs(banco) == []


def test_criar_calcula_a_proxima_versao_e_o_hash_dela(emissor, flags):
    banco = PostgrestFalso()
    banco.responder("GET", "governanca_artefatos", 200, [{"id": "art-1"}])
    banco.responder("GET", "governanca_versoes", 200, [{"versao": 3}])
    banco.responder("POST", "governanca_criar_versao", 200, VERSAO)
    r = _api_com(emissor, banco).post(f"{BASE}/artefatos", headers=_h(emissor, papel="admin"), json={
        "tipo": "clausula", "chave": "clausula.tr.garantia", "payload": CLAUSULA})
    assert r.status_code == 201, r.text
    corpo = banco.corpo(_rpcs(banco)[-1])
    esperado = governanca.nova_versao_artefato("clausula", "clausula.tr.garantia", CLAUSULA, versao=4)
    assert corpo["p_versao"] == 4 and corpo["p_hash"] == esperado["hash"]


LIDO = "2026-10-27T10:00:00+00:00"
IF_MATCH = {"If-Match": f'"{LIDO}"'}


@pytest.mark.parametrize("codigo,status", [("42501", 403), ("22023", 422), ("40001", 409), ("55000", 409)])
def test_o_codigo_do_banco_decide_o_http(emissor, flags, codigo, status):
    banco = PostgrestFalso()
    banco.responder("POST", "governanca_transicionar", 400, {"code": codigo, "message": "x"})
    r = _api_com(emissor, banco).post(f"{BASE}/versoes/{VERSAO}/transicao", headers={**_h(emissor, papel="admin"), **IF_MATCH},
                                      json={"status": "PUBLISHED"})
    assert r.status_code == status


def test_superar_nao_e_pedido_e_status_fora_do_vocabulario_e_422(emissor, flags):
    banco = PostgrestFalso()
    api = _api_com(emissor, banco)
    for status in ("SUPERSEDED", "QUALQUER"):
        assert api.post(f"{BASE}/versoes/{VERSAO}/transicao", headers={**_h(emissor, papel="admin"), **IF_MATCH},
                        json={"status": status}).status_code == 422
    assert _rpcs(banco) == []


def test_transicionar_exige_if_match_e_manda_a_versao_lida(emissor, flags):
    banco = PostgrestFalso()
    api = _api_com(emissor, banco)
    assert api.post(f"{BASE}/versoes/{VERSAO}/transicao", headers=_h(emissor, papel="admin"),
                    json={"status": "UNDER_REVIEW"}).status_code == 428
    assert _rpcs(banco) == []
    banco.responder("POST", "governanca_transicionar", 200, "UNDER_REVIEW")
    r = api.post(f"{BASE}/versoes/{VERSAO}/transicao", headers={**_h(emissor, papel="admin"), **IF_MATCH},
                 json={"status": "UNDER_REVIEW"})
    assert r.status_code == 200, r.text
    corpo = banco.corpo(_rpcs(banco)[-1])
    assert corpo["p_esperado"] == LIDO and corpo["p_novo"] == "UNDER_REVIEW"


def test_editar_exige_if_match_e_manda_a_versao_lida(emissor, flags):
    banco = PostgrestFalso()
    api = _api_com(emissor, banco)
    assert api.put(f"{BASE}/versoes/{VERSAO}", headers=_h(emissor, papel="admin"),
                   json={"payload": CLAUSULA}).status_code == 428
    banco.responder("GET", "governanca_versoes", 200, [{
        "id": VERSAO, "versao": 2, "status": "DRAFT", "atualizado_em": "2026-10-27T10:00:00+00:00",
        "artefato": {"tipo_artefato": "clausula", "chave_estavel": "clausula.tr.garantia", "tenant_id": TENANT_A}}])
    banco.responder("POST", "governanca_editar_rascunho", 200, "2026-10-27T10:01:00+00:00")
    r = api.put(f"{BASE}/versoes/{VERSAO}", headers={**_h(emissor, papel="admin"),
                                                     "If-Match": '"2026-10-27T10:00:00+00:00"'},
                json={"payload": CLAUSULA})
    assert r.status_code == 200, r.text
    corpo = banco.corpo(_rpcs(banco)[-1])
    assert corpo["p_esperado"] == "2026-10-27T10:00:00+00:00"
    assert corpo["p_hash"] == governanca.nova_versao_artefato(
        "clausula", "clausula.tr.garantia", CLAUSULA, versao=2, status="DRAFT")["hash"]


def test_versao_de_outro_municipio_e_404_sem_rpc(emissor, flags):
    banco = PostgrestFalso()
    banco.responder("GET", "governanca_versoes", 200, [{
        "id": VERSAO, "versao": 1, "status": "DRAFT", "atualizado_em": "x",
        "artefato": {"tipo_artefato": "clausula", "chave_estavel": "c.x.y", "tenant_id": "outro"}}])
    r = _api_com(emissor, banco).put(f"{BASE}/versoes/{VERSAO}", headers={**_h(emissor, papel="admin"),
                                                                          "If-Match": '"x"'},
                                     json={"payload": CLAUSULA})
    assert r.status_code == 404 and _rpcs(banco) == []


def test_derivar_manda_o_hash_da_versao_nova(emissor, flags):
    banco = PostgrestFalso()
    banco.responder("GET", "governanca_versoes", 200, [{
        "payload": CLAUSULA, "artefato_id": "art-1",
        "artefato": {"tipo_artefato": "clausula", "chave_estavel": "clausula.tr.garantia", "tenant_id": TENANT_A}}])
    banco.responder("GET", "governanca_versoes", 200, [{"versao": 2}])
    banco.responder("POST", "governanca_derivar_versao", 200, VERSAO)
    r = _api_com(emissor, banco).post(f"{BASE}/versoes/{VERSAO}/derivacao", headers=_h(emissor, papel="admin"))
    assert r.status_code == 201, r.text
    corpo = banco.corpo(_rpcs(banco)[-1])
    assert corpo["p_proxima"] == 3 and corpo["p_hash"] == governanca.nova_versao_artefato(
        "clausula", "clausula.tr.garantia", CLAUSULA, versao=3)["hash"]


def test_escrita_com_centro_desligado_e_404_e_sem_papel_e_403(emissor, flags):
    banco = PostgrestFalso()
    api = _api_com(emissor, banco)
    assert api.post(f"{BASE}/versoes/{VERSAO}/transicao", headers={**_h(emissor), **IF_MATCH},
                    json={"status": "UNDER_REVIEW"}).status_code == 403
    flags[governanca.FLAG_CENTRO] = False
    assert api.post(f"{BASE}/versoes/{VERSAO}/transicao", headers={**_h(emissor, papel="admin"), **IF_MATCH},
                    json={"status": "UNDER_REVIEW"}).status_code == 404
    assert _rpcs(banco) == []
