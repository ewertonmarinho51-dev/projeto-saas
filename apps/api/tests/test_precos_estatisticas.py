"""
Estatísticas do item contra PostgREST SIMULADO.

O que se prova: a conta é a do domínio (`estatistica.calcular`), exata e em
string; a cesta e as coletadas são séries separadas; "fora da faixa" é
medido contra a CESTA; o item tem de ser da pesquisa; flag desligada é 404.
Isolamento real (RLS da 0021) é `tests_rls/test_rls_precos.py`.
"""

import httpx
import pytest
from fastapi.testclient import TestClient

from govconect_api.config import carregar
from govconect_api.main import criar_app
from govconect_api.precos_estatisticas import estatisticas_do_item
from govconect_api.verificador import VerificadorSupabase

from apoio_jwt import EMISSOR, TENANT_A, Emissor, PostgrestFalso

PESQUISA = "dddddddd-0000-4000-8000-000000000001"
ITEM = "eeeeeeee-0000-4000-8000-000000000001"
URL = f"/api/v1/precos/pesquisas/{PESQUISA}/itens/{ITEM}/estatisticas"


@pytest.fixture
def emissor():
    return Emissor()


@pytest.fixture
def banco():
    return PostgrestFalso()


@pytest.fixture
def api(emissor, banco):
    def montar(precos=True):
        config = carregar({"APP_ENV": "test",
                           "SUPABASE_URL": "https://exemplo-staging.supabase.co",
                           "SUPABASE_KEY": "chave-publicavel-de-teste",
                           "PRICE_RESEARCH_ENABLED": "1" if precos else "0"})
        rest = banco.cliente()
        verificador = VerificadorSupabase(emissor=EMISSOR, rest=rest,
                                          chave_para=emissor.chave_para)
        return TestClient(criar_app(config, verificador=verificador, rest=rest),
                          raise_server_exceptions=False)
    return montar


def _auth(emissor):
    return {"Authorization": f"Bearer {emissor.token()}"}


def _bruto(texto: str) -> httpx.Response:
    return httpx.Response(200, content=texto.encode(),
                          headers={"content-type": "application/json"})


def _ref(ident, valor, status, fonte, uf):
    valor_json = "null" if valor is None else valor
    uf_json = "null" if uf is None else f'"{uf}"'
    return (f'{{"id": "{ident}", "fonte_id": "{fonte.lower()}", "fonte_nome": "{fonte}",'
            f' "fonte_tipo": "sistema_oficial", "natureza_valor": "homologado",'
            f' "status": "{status}", "descricao_original": "Luva",'
            f' "valor_unitario_normalizado": {valor_json}, "uf": {uf_json},'
            f' "coletado_em": "2026-10-20T10:00:00+00:00", "motivos": [], "bruto": {{}}}}')


# Cesta: 10, 11, 12, 13 e 40 (o 40 em `warning` ainda está na cesta).
# Fora dela: 50 (candidata), 9 (rejeitada) e uma sem valor normalizado.
SERIE = "[" + ",".join([
    _ref("r09", "9.00", "rejected", "Compras.gov", "PA"),
    _ref("r10", "10.00", "selected", "PNCP", "pa"),
    _ref("r11", "11.00", "selected", "PNCP", "PA"),
    _ref("r12", "12.00", "selected", "PNCP", None),
    _ref("r13", "13.00", "selected", "Compras.gov", "SP"),
    _ref("r40", "40.00", "warning", "Compras.gov", "SP"),
    _ref("r50", "50.00", "candidate", "PNCP", "SP"),
    _ref("rnn", None, "candidate", "PNCP", "PA"),
]) + "]"


def test_flag_desligada_e_404(api, emissor):
    assert api(precos=False).get(URL, headers=_auth(emissor)).status_code == 404


def test_sem_credencial_e_401(api):
    assert api().get(URL).status_code == 401


def test_item_de_outra_pesquisa_e_404_e_nao_le_referencias(api, emissor, banco):
    banco.respostas[("GET", "pesquisa_preco_itens")] = [_bruto("[]")]
    r = api().get(URL, headers=_auth(emissor))
    assert r.status_code == 404
    filtro = banco.chamadas[-1].url.params
    assert filtro["pesquisa_id"] == f"eq.{PESQUISA}" and filtro["id"] == f"eq.{ITEM}"
    assert filtro["tenant_id"] == f"eq.{TENANT_A}"
    assert all("referencias" not in str(c.url) for c in banco.chamadas)


def test_conta_exata_da_cesta_e_das_coletadas(api, emissor, banco):
    banco.respostas[("GET", "pesquisa_preco_itens")] = [_bruto('[{"id": "%s"}]' % ITEM)]
    banco.respostas[("GET", "pesquisa_preco_referencias")] = [_bruto(SERIE)]
    r = api().get(URL, headers=_auth(emissor))
    assert r.status_code == 200, r.text
    corpo = r.json()
    assert banco.chamadas[-1].url.params["tenant_id"] == f"eq.{TENANT_A}"

    cesta = corpo["cesta"]
    assert cesta["quantidade"] == 5
    assert cesta["media"] == {"valor": "17.2000", "exibicao": "R$ 17,20"}     # 86 ÷ 5
    assert cesta["mediana"]["valor"] == "12.0000"
    assert (cesta["q1"]["valor"], cesta["q3"]["valor"]) == ("11.0000", "13.0000")
    assert cesta["amplitude"]["exibicao"] == "R$ 30,00"
    # desvio amostral √(654,8 ÷ 4) = 12,7945…; CV = 12,7945 ÷ 17,2
    assert cesta["desvio_padrao"]["exibicao"] == "R$ 12,79"
    assert cesta["coeficiente_variacao"] == {"valor": "0.7439", "exibicao": "74,39%"}
    assert cesta["dispersao"] == "dispersa"
    assert cesta["faixa_usual"] == {"minimo": {"valor": "8.0000", "exibicao": "R$ 8,00"},
                                    "maximo": {"valor": "16.0000", "exibicao": "R$ 16,00"}}

    coletadas = corpo["coletadas"]
    assert coletadas["quantidade"] == 7
    assert (coletadas["menor"]["valor"], coletadas["maior"]["valor"]) == ("9.0000", "50.0000")
    assert corpo["sem_valor"] == 1
    assert corpo["limite_dispersao"] == {"valor": "0.2500", "exibicao": "25,00%"}


def test_pontos_e_faixa_contra_a_cesta(api, emissor, banco):
    banco.respostas[("GET", "pesquisa_preco_itens")] = [_bruto('[{"id": "%s"}]' % ITEM)]
    banco.respostas[("GET", "pesquisa_preco_referencias")] = [_bruto(SERIE)]
    pontos = {p["referencia_id"]: p for p in api().get(URL, headers=_auth(emissor)).json()["pontos"]}
    assert set(pontos) == {"r09", "r10", "r11", "r12", "r13", "r40", "r50"}
    assert pontos["r40"]["fora_da_faixa"] == ["IQR", "MAD"]
    assert pontos["r50"]["fora_da_faixa"] == ["IQR", "MAD"] and not pontos["r50"]["na_cesta"]
    # 9 fica dentro da faixa 8–16 e a 3 da mediana (corte MAD 4,4478)
    assert pontos["r09"]["fora_da_faixa"] == [] and not pontos["r09"]["na_cesta"]
    assert pontos["r40"]["na_cesta"] and pontos["r40"]["status"] == "warning"
    assert pontos["r40"]["valor"] == {"valor": "40.0000", "exibicao": "R$ 40,00"}


def test_comparacao_por_fonte_e_por_uf(api, emissor, banco):
    banco.respostas[("GET", "pesquisa_preco_itens")] = [_bruto('[{"id": "%s"}]' % ITEM)]
    banco.respostas[("GET", "pesquisa_preco_referencias")] = [_bruto(SERIE)]
    corpo = api().get(URL, headers=_auth(emissor)).json()
    fontes = [(g["rotulo"], g["resumo"]["quantidade"], g["na_cesta"]) for g in corpo["por_fonte"]]
    assert fontes == [("PNCP", 4, 3), ("Compras.gov", 3, 2)]
    assert corpo["por_fonte"][0]["resumo"]["mediana"]["valor"] == "11.5000"
    ufs = {g["rotulo"]: g["resumo"]["quantidade"] for g in corpo["por_uf"]}
    assert ufs == {"PA": 3, "SP": 3, "Sem UF": 1}                     # "pa" conta como PA


def test_serie_curta_nao_inventa_dispersao_nem_faixa():
    so_um = estatisticas_do_item([{"id": "a", "status": "selected",
                                   "valor_unitario_normalizado": "7.5000"}])
    assert so_um.cesta.dispersao == "insuficiente" and so_um.cesta.faixa_usual is None
    vazio = estatisticas_do_item([{"id": "b", "status": "selected",
                                   "valor_unitario_normalizado": None}])
    assert vazio.cesta is None and vazio.coletadas is None and vazio.sem_valor == 1
    assert vazio.pontos == [] and vazio.por_fonte == []


def test_float_no_dinheiro_falha_alto():
    with pytest.raises(TypeError):
        estatisticas_do_item([{"id": "c", "status": "selected",
                               "valor_unitario_normalizado": 1.1}])
