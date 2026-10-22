"""
Tradução HTTP ↔ domínio da cesta, com o serviço do domínio SUBSTITUÍDO.

Aqui se prova o que é desta camada: If-Match obrigatório, 404 antes do
domínio, o token e o tenant VERIFICADOS dentro da sessão do domínio (e
só durante a chamada), cada exceção do domínio no código HTTP certo, e
dinheiro de volta como string. A regra da cesta em si é provada pelas
suítes do domínio (tests/test_cotacoes_*) e, com banco real, pelo
`tests_rls/test_rls_cesta.py`.
"""

from decimal import Decimal
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from govconect_api.config import carregar
from govconect_api.main import criar_app
from govconect_api.verificador import VerificadorSupabase
from src import db
from src.precos import cotacoes
from src.precos import repositorio as repo
from src.streamlit_opcional import st

from apoio_jwt import EMISSOR, TENANT_A, USUARIO_A, Emissor, PostgrestFalso

P = "dddddddd-0000-4000-8000-000000000001"
I = "eeeeeeee-0000-4000-8000-000000000001"
R = "ffffffff-0000-4000-8000-000000000001"
URL = f"/api/v1/precos/pesquisas/{P}/itens/{I}/referencias/{R}"


@pytest.fixture
def emissor():
    return Emissor()


@pytest.fixture
def banco():
    b = PostgrestFalso()
    b.responder("GET", "pesquisa_preco_itens", 200,
                [{"id": I, "estado": "review", "pesquisa": {"auth_user_id": USUARIO_A}}])
    return b


@pytest.fixture
def api(emissor, banco):
    config = carregar({"APP_ENV": "test", "SUPABASE_URL": "https://exemplo-staging.supabase.co",
                       "SUPABASE_KEY": "chave-publicavel-de-teste", "PRICE_RESEARCH_ENABLED": "1"})
    rest = banco.cliente()
    verificador = VerificadorSupabase(emissor=EMISSOR, rest=rest, chave_para=emissor.chave_para)
    return TestClient(criar_app(config, verificador=verificador, rest=rest),
                      raise_server_exceptions=False)


def _h(emissor, revisao="3"):
    h = {"Authorization": f"Bearer {emissor.token()}"}
    if revisao is not None:
        h["If-Match"] = f'"{revisao}"'
    return h


@pytest.fixture
def dominio(monkeypatch):
    chamadas = []

    def alterar(ctx, pid, iid, rid, *, incluir, motivo, revisao_esperada):
        # O que o domínio ENXERGA durante a chamada: a sessão da requisição.
        chamadas.append({"ctx": ctx, "ids": (pid, iid, rid), "incluir": incluir,
                         "motivo": motivo, "revisao": revisao_esperada,
                         "token": st.session_state.get(db.CHAVE_DA_SESSAO),
                         "tenant": db.tenant_atual()})
        if isinstance(alterar.erro, Exception):
            raise alterar.erro
        return SimpleNamespace(valor_unitario=Decimal("2.3450"), metodo="mediana",
                               status="CONCLUIDO", pendencias=[])

    alterar.erro = None
    monkeypatch.setattr(cotacoes, "alterar_status_referencia", alterar)
    monkeypatch.setattr(repo, "obter_item", lambda iid: {"id": iid, "revisao": 4})
    alterar.chamadas = chamadas
    return alterar


def test_tirar_recalcula_e_devolve_revisao_nova(api, emissor, dominio):
    r = api.patch(URL, headers=_h(emissor), json={"incluir": False})
    assert r.status_code == 200, r.text
    assert r.json() == {"preco_estimado": {"valor": "2.3450", "exibicao": "R$ 2,35"},
                        "metodo": "mediana", "status": "CONCLUIDO", "pendencias": [],
                        "revisao": 4}
    (c,) = dominio.chamadas
    assert c["ids"] == (P, I, R) and c["revisao"] == 3 and c["incluir"] is False
    assert c["ctx"].auth_user_id == USUARIO_A
    # O domínio viu o token e o tenant da identidade VERIFICADA...
    assert c["token"] and c["tenant"] == TENANT_A
    # ...e nada sobra depois da requisição.
    assert st.session_state.get(db.CHAVE_DA_SESSAO) is None


def test_sem_if_match_e_428_sem_tocar_o_dominio(api, emissor, dominio):
    r = api.patch(URL, headers=_h(emissor, revisao=None), json={"incluir": False})
    assert r.status_code == 428
    assert dominio.chamadas == []


def test_item_fora_do_acesso_e_404_sem_tocar_o_dominio(api, emissor, banco, dominio):
    banco.respostas[("GET", "pesquisa_preco_itens")] = []
    banco.responder("GET", "pesquisa_preco_itens", 200, [])
    r = api.patch(URL, headers=_h(emissor), json={"incluir": False})
    assert r.status_code == 404
    assert dominio.chamadas == []


@pytest.mark.parametrize("erro, status, codigo", [
    (repo.ConflitoDeVersao("x"), 409, "VERSION_CONFLICT"),
    (cotacoes.CotacaoImutavel("x"), 409, "IMMUTABLE"),
    (cotacoes.ErroCotacao("registre o motivo da inclusão"), 422, "DOMAIN_RULE"),
    (repo.SemSessao("x"), 401, "UNAUTHENTICATED"),
    (db.ErroBanco("https://x.supabase.co?apikey=segredo"), 503, "DATABASE_UNAVAILABLE"),
])
def test_excecoes_do_dominio_viram_o_codigo_certo(api, emissor, dominio, erro, status, codigo):
    dominio.erro = erro
    r = api.patch(URL, headers=_h(emissor), json={"incluir": True, "motivo": "teste"})
    assert r.status_code == status
    assert r.json()["code"] == codigo
    assert "apikey" not in r.text


def test_mensagem_do_dominio_chega_ao_usuario(api, emissor, dominio):
    dominio.erro = cotacoes.ErroCotacao("registre o motivo da inclusão: ele vai para a memória de cálculo")
    r = api.patch(URL, headers=_h(emissor), json={"incluir": True})
    assert "registre o motivo da inclusão" in r.json()["message"]


def test_corpo_com_campo_extra_e_422(api, emissor, dominio):
    r = api.patch(URL, headers=_h(emissor), json={"incluir": False, "status": "selected"})
    assert r.status_code == 422
    assert dominio.chamadas == []


def test_flag_desligada_e_404(emissor, banco, dominio):
    config = carregar({"APP_ENV": "test", "SUPABASE_URL": "https://exemplo-staging.supabase.co",
                       "SUPABASE_KEY": "chave-publicavel-de-teste"})
    rest = banco.cliente()
    app = criar_app(config, verificador=VerificadorSupabase(
        emissor=EMISSOR, rest=rest, chave_para=emissor.chave_para), rest=rest)
    r = TestClient(app).patch(URL, headers=_h(emissor), json={"incluir": False})
    assert r.status_code == 404
    assert dominio.chamadas == []


def test_dominio_usa_a_mesma_configuracao_da_api(api):
    # A fixture `api` montou o app com SUPABASE_URL/KEY só no dicionário de
    # configuração, nada no ambiente. O domínio tem de enxergar os mesmos.
    assert db._segredo("SUPABASE_URL") == "https://exemplo-staging.supabase.co"
    assert db._segredo(db.NOME_CHAVE_PUBLICA) == "chave-publicavel-de-teste"


def test_chave_de_servidor_nunca_vai_para_o_dominio():
    from src.streamlit_opcional import configurar_supabase

    with pytest.raises(ValueError):
        configurar_supabase("https://x.exemplo.co", "sb_secret_" + "x" * 20)


def test_quem_nao_e_dono_nem_admin_e_403_sem_tocar_o_dominio(api, emissor, banco, dominio):
    banco.respostas[("GET", "pesquisa_preco_itens")] = []
    banco.responder("GET", "pesquisa_preco_itens", 200, [
        {"id": I, "estado": "review",
         "pesquisa": {"auth_user_id": "dddddddd-0000-4000-8000-000000000009"}}])
    r = api.patch(URL, headers=_h(emissor), json={"incluir": False})
    assert r.status_code == 403
    assert dominio.chamadas == []


def test_admin_do_municipio_pode_mexer_na_cesta_alheia(api, emissor, banco, dominio):
    banco.respostas[("GET", "pesquisa_preco_itens")] = []
    banco.responder("GET", "pesquisa_preco_itens", 200, [
        {"id": I, "estado": "review",
         "pesquisa": {"auth_user_id": "dddddddd-0000-4000-8000-000000000009"}}])
    r = api.patch(URL, headers={**_h(emissor), "Authorization": f"Bearer {emissor.token(papel='admin')}"},
                  json={"incluir": False})
    assert r.status_code == 200, r.text


def test_item_concluido_exige_reabrir_antes(api, emissor, banco, dominio):
    # Apontado na revisão: a tela do Streamlit esconde a cesta de item
    # concluído e reabrir exige motivo + evento. A API não pode furar isso.
    banco.respostas[("GET", "pesquisa_preco_itens")] = []
    banco.responder("GET", "pesquisa_preco_itens", 200,
                    [{"id": I, "estado": "complete", "pesquisa": {"auth_user_id": USUARIO_A}}])
    r = api.patch(URL, headers=_h(emissor), json={"incluir": False})
    assert r.status_code == 409
    assert r.json()["code"] == "ITEM_COMPLETE"
    assert dominio.chamadas == []
