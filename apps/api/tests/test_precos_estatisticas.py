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


def _linha(ident, valor, status="selected", data=None):
    return {"id": ident, "status": status, "valor_unitario_normalizado": valor,
            "data_compra": data}


def _serie(valores, **kw):
    return [_linha(f"r{i}", v, **kw) for i, v in enumerate(valores)]


def test_eixo_e_linear_contem_tudo_e_vem_escrito():
    d = estatisticas_do_item(_serie(["10.00", "11.00", "12.00", "13.00", "40.00"]))
    assert (d.escala.minimo.valor, d.escala.maximo.valor) == ("0.0000", "40.0000")
    assert [m.exibicao for m in d.escala.marcas] == [
        "R$ 0,00", "R$ 10,00", "R$ 20,00", "R$ 30,00", "R$ 40,00"]
    # Marcas equidistantes: eixo quebrado daria passos diferentes.
    marcas = [float(m.valor) for m in d.escala.marcas]
    assert {round(b - a, 4) for a, b in zip(marcas, marcas[1:])} == {10.0}


def test_eixo_nao_perde_centavos_nem_preco_unico():
    assert [m.exibicao for m in estatisticas_do_item(_serie(["2.35"])).escala.marcas] == [
        "R$ 2,10", "R$ 2,20", "R$ 2,30", "R$ 2,40", "R$ 2,50", "R$ 2,60"]
    pequenos = estatisticas_do_item(_serie(["0.0100", "0.0101"])).escala
    textos = [m.exibicao for m in pequenos.marcas]
    assert len(textos) == len(set(textos)), textos


def test_eixo_alcanca_a_faixa_usual_desenhada():
    d = estatisticas_do_item(_serie(["100.00", "101.00", "102.00", "103.00"]))
    assert float(d.escala.maximo.valor) >= float(d.cesta.faixa_usual.maximo.valor)
    assert float(d.escala.minimo.valor) <= float(d.cesta.faixa_usual.minimo.valor)


def test_extremos_sao_de_todas_as_coletadas_e_nomeados():
    linhas = [*_serie(["10.00", "11.00", "12.00", "13.00"]),
              _linha("fora", "9800.00", status="rejected"), _linha("baixo", "1.00", status="candidate")]
    pontos = {p.referencia_id: p for p in estatisticas_do_item(linhas).pontos}
    assert pontos["fora"].extremo == "maior" and pontos["baixo"].extremo == "menor"
    assert pontos["r1"].extremo is None
    # Mediana da cesta 11,50: o extremo traz a distância verdadeira, com sinal.
    assert pontos["fora"].sobre_a_mediana.exibicao == "+85117,39%"
    assert pontos["baixo"].sobre_a_mediana.exibicao == "-91,30%"


def test_empate_no_extremo_marca_os_dois_e_serie_igual_nao_tem_extremo():
    pontos = estatisticas_do_item(_serie(["5.00", "5.00", "7.00"])).pontos
    assert [p.extremo for p in pontos] == ["menor", "menor", "maior"]
    iguais = estatisticas_do_item(_serie(["5.00", "5.00"])).pontos
    assert [p.extremo for p in iguais] == [None, None]


def test_recorte_so_aparece_quando_o_extremo_achata_e_nao_some_com_ninguem():
    linhas = [*_serie(["10.00", "11.00", "12.00", "13.00"]), _linha("x", "9800.00", status="candidate")]
    d = estatisticas_do_item(linhas)
    assert d.escala.maximo.valor == "10000.0000"     # o eixo principal segue inteiro
    assert (d.recorte.abaixo, d.recorte.acima) == (0, 1)
    assert float(d.recorte.escala.maximo.valor) < 20
    # Quem está dentro do eixo ampliado + quem foi contado fora = todos.
    fim = float(d.recorte.escala.maximo.valor)
    inicio = float(d.recorte.escala.minimo.valor)
    dentro = [p for p in d.pontos if inicio <= float(p.valor.valor) <= fim]
    assert len(dentro) + d.recorte.abaixo + d.recorte.acima == len(d.pontos)

    assert estatisticas_do_item(_serie(["10.00", "11.00", "12.00", "13.00"])).recorte is None
    assert estatisticas_do_item(_serie(["10.00", "99.00"])).recorte is None   # abaixo de 4


def test_tendencia_segue_a_data_e_exige_tres_datados():
    linhas = [_linha("a", "30.00", data="2026-03-01"), _linha("b", "10.00", data="2026-01-01"),
              _linha("c", "20.00", data="2026-02-01"), _linha("sem", "99.00"),
              _linha("fora", "77.00", status="rejected", data="2026-02-15")]
    assert [v.exibicao for v in estatisticas_do_item(linhas).tendencia] == [
        "R$ 10,00", "R$ 20,00", "R$ 30,00"]
    assert estatisticas_do_item(linhas[:2]).tendencia == []


def test_recorte_nao_aparece_se_a_faixa_central_ja_ocupa_metade_do_eixo():
    # 60 está fora da faixa usual (até 55), mas não achata nada: o eixo vai a 60.
    linhas = [*_serie(["10.00", "20.00", "30.00", "40.00"]), _linha("x", "60.00", status="candidate")]
    assert estatisticas_do_item(linhas).recorte is None
