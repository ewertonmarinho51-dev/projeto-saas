"""
Leitura de pesquisas de preços contra PostgREST SIMULADO.

O que se prova aqui é o contrato: dinheiro exato como string, mesma
regra de arredondamento do relatório, link só de host oficial, item
amarrado à pesquisa, flag desligada como 404. Isolamento real (RLS da
0021) é `tests_rls/test_rls_precos.py`.
"""

import httpx
import pytest
from fastapi.testclient import TestClient

from govconect_api.config import carregar
from govconect_api.main import criar_app
from govconect_api.verificador import VerificadorSupabase

from apoio_jwt import EMISSOR, TENANT_A, Emissor, PostgrestFalso

PESQUISA = "dddddddd-0000-4000-8000-000000000001"
ITEM = "eeeeeeee-0000-4000-8000-000000000001"


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
    """Resposta com o JSON CRU, como o PostgREST manda `numeric`."""
    return httpx.Response(200, content=texto.encode(),
                          headers={"content-type": "application/json"})


def test_flag_desligada_e_404_mesmo_autenticado(api, emissor):
    r = api(precos=False).get("/api/v1/precos/pesquisas", headers=_auth(emissor))
    assert r.status_code == 404


def test_sem_credencial_e_401_antes_da_flag(api):
    assert api(precos=False).get("/api/v1/precos/pesquisas").status_code == 401


def test_dinheiro_chega_exato_e_sai_como_string(api, emissor, banco):
    # 12345678901234.5678 não cabe em float: lido como float viraria
    # 12345678901234.568. A resposta tem de trazer os 4 dígitos.
    banco.respostas[("GET", "pesquisas_preco")] = [_bruto(
        '[{"id": "%s", "nome": "Luvas", "objeto": "", "estado": "review",'
        ' "valor_global": 12345678901234.5678, "atualizado_em": "2026-10-22T14:00:00+00:00"}]'
        % PESQUISA)]
    r = api().get("/api/v1/precos/pesquisas", headers=_auth(emissor))
    assert r.status_code == 200
    valor = r.json()["itens"][0]["valor_global"]
    assert valor == {"valor": "12345678901234.5678", "exibicao": "R$ 12.345.678.901.234,57"}
    chamada = banco.chamadas[-1]
    assert chamada.url.params["tenant_id"] == f"eq.{TENANT_A}"
    assert chamada.url.params["estado"] == "neq.archived"


def test_meio_centavo_arredonda_como_o_relatorio(api, emissor, banco):
    banco.respostas[("GET", "pesquisas_preco")] = [_bruto(
        '[{"id": "%s", "nome": "x", "objeto": "", "estado": "review", "valor_global": 0.005,'
        ' "data_base": null, "responsavel": "", "local_referencia": "", "processo_id": null,'
        ' "versao": 1, "criado_em": "x", "atualizado_em": "x"}]' % PESQUISA)]
    banco.respostas[("GET", "pesquisa_preco_itens")] = [_bruto(
        '[{"id": "%s", "numero": 1, "codigo": "451234", "tipo_catalogo": "CATMAT",'
        ' "descricao": "Luva", "unidade": "CX", "quantidade": 1500.0000, "estado": "complete",'
        ' "metodo": "mediana", "preco_estimado": 2.3450, "preco_total": 3517.5000,'
        ' "justificativa": ""}]' % ITEM)]
    r = api().get(f"/api/v1/precos/pesquisas/{PESQUISA}", headers=_auth(emissor))
    assert r.status_code == 200, r.text
    corpo = r.json()
    assert corpo["valor_global"]["exibicao"] == "R$ 0,01"          # ROUND_HALF_UP
    item = corpo["itens"][0]
    assert banco.chamadas[-1].url.params["removido_em"] == "is.null"
    assert item["preco_estimado"] == {"valor": "2.3450", "exibicao": "R$ 2,35"}
    assert item["quantidade"] == {"valor": "1500.0000", "exibicao": "1.500"}
    assert item["preco_total"]["exibicao"] == "R$ 3.517,50"


def test_pesquisa_alheia_ou_inexistente_e_404(api, emissor, banco):
    banco.respostas[("GET", "pesquisas_preco")] = [_bruto("[]")]
    r = api().get(f"/api/v1/precos/pesquisas/{PESQUISA}", headers=_auth(emissor))
    assert r.status_code == 404


def test_referencias_exigem_item_da_mesma_pesquisa(api, emissor, banco):
    banco.respostas[("GET", "pesquisa_preco_itens")] = [_bruto("[]")]
    r = api().get(f"/api/v1/precos/pesquisas/{PESQUISA}/itens/{ITEM}/referencias",
                  headers=_auth(emissor))
    assert r.status_code == 404
    filtro = banco.chamadas[-1].url.params
    assert filtro["pesquisa_id"] == f"eq.{PESQUISA}" and filtro["id"] == f"eq.{ITEM}"


def test_link_so_de_host_oficial_e_bruto_nao_sai(api, emissor, banco):
    banco.respostas[("GET", "pesquisa_preco_itens")] = [_bruto('[{"id": "%s"}]' % ITEM)]
    banco.respostas[("GET", "pesquisa_preco_referencias")] = [_bruto("""[
      {"id": "f1", "fonte_id": "pncp", "fonte_nome": "PNCP", "fonte_tipo": "sistema_oficial",
       "natureza_valor": "homologado", "status": "selected", "descricao_original": "Luva",
       "valor_unitario_original": 2.3456, "valor_unitario_normalizado": 2.3456,
       "coletado_em": "2026-10-20T10:00:00+00:00", "motivos": [],
       "bruto": {"numeroControlePNCP": "12345678000190-1-000123/2025", "segredo": "nao-sai"}},
      {"id": "f2", "fonte_id": "outra", "fonte_nome": "Painel X", "fonte_tipo": "outro",
       "natureza_valor": "outro", "status": "candidate", "descricao_original": "Luva",
       "referencia_externa": "http://169.254.169.254/latest/meta-data",
       "valor_unitario_original": 1.0, "coletado_em": "x", "motivos": ["fora_da_faixa"],
       "bruto": {"url": "http://127.0.0.1/admin"}}
    ]""")]
    r = api().get(f"/api/v1/precos/pesquisas/{PESQUISA}/itens/{ITEM}/referencias",
                  headers=_auth(emissor))
    assert r.status_code == 200, r.text
    oficial, outra = r.json()
    assert oficial["link_contratacao"] == "https://pncp.gov.br/app/editais/12345678000190/2025/123"
    assert oficial["valor_unitario_normalizado"]["valor"] == "2.3456"
    assert outra["link_contratacao"] is None and outra["link_fonte"] is None
    assert "169.254" not in r.text and "127.0.0.1" not in r.text and "nao-sai" not in r.text
    assert outra["motivos"] == ["fora_da_faixa"]


def test_float_no_caminho_do_dinheiro_falha_alto():
    from govconect_api.precos import valor_monetario

    with pytest.raises(TypeError):
        valor_monetario(0.1)


def _pesquisa_com_totais(banco, *totais):
    banco.respostas[("GET", "pesquisas_preco")] = [_bruto(
        '[{"id": "%s", "nome": "x", "objeto": "", "estado": "review", "valor_global": null,'
        ' "data_base": null, "responsavel": "", "local_referencia": "", "processo_id": null,'
        ' "versao": 1, "criado_em": "x", "atualizado_em": "x"}]' % PESQUISA)]
    linhas = ",".join(
        '{"id": "item-%d", "numero": %d, "descricao": "x", "unidade": "UN", "quantidade": 1,'
        ' "estado": "review", "preco_total": %s, "justificativa": ""}' % (n, n, t)
        for n, t in enumerate(totais, start=1))
    banco.respostas[("GET", "pesquisa_preco_itens")] = [_bruto(f"[{linhas}]")]


def test_soma_dos_itens_e_exata_e_ignora_item_sem_preco(api, emissor, banco):
    # Em float, 0.1 + 0.2 daria 0.30000000000000004.
    _pesquisa_com_totais(banco, "0.1000", "0.2000", "null", "11165.0000")
    corpo = api().get(f"/api/v1/precos/pesquisas/{PESQUISA}", headers=_auth(emissor)).json()
    assert corpo["valor_global"] is None
    assert corpo["soma_dos_itens"] == {"valor": "11165.3000", "exibicao": "R$ 11.165,30"}


def test_sem_item_com_preco_nao_afirma_soma_zero(api, emissor, banco):
    _pesquisa_com_totais(banco, "null", "null")
    corpo = api().get(f"/api/v1/precos/pesquisas/{PESQUISA}", headers=_auth(emissor)).json()
    assert corpo["soma_dos_itens"] is None


# ---------------------------------------------------------------------------
# Barreira do CV da cotação automática no item (10/11/2026)
# ---------------------------------------------------------------------------
_PESQUISA_MINIMA = ('[{"id": "%s", "nome": "x", "objeto": "", "estado": "review", "valor_global": null,'
                    ' "data_base": null, "responsavel": "", "local_referencia": "", "processo_id": null,'
                    ' "versao": 1, "criado_em": "x", "atualizado_em": "x"}]' % PESQUISA)
_ITEM_MINIMO = ('{"id": "%s", "numero": 1, "codigo": null, "tipo_catalogo": null, "descricao": "Luva",'
                ' "unidade": "CX", "quantidade": 1, "estado": "incomplete", "metodo": null,'
                ' "preco_estimado": null, "preco_total": null, "justificativa": "", "barreira_cv": %s}')


@pytest.mark.parametrize("gravado, esperado", [
    ('{"aprovada": false, "motivo": "cv_acima_do_limite", "cv": "0.3", "cv_exibicao": "30,00%",'
     ' "quantidade": 3, "novas": 3, "texto": "3 referência(s) aguardam revisão"}',
     {"motivo": "cv_acima_do_limite", "cv": "30,00%", "limite": "25%", "quantidade": 3,
      "sugeridas": 3, "texto": "3 referência(s) aguardam revisão"}),
    ('{"aprovada": false, "motivo": "cv_indisponivel", "cv": null, "cv_exibicao": null,'
     ' "quantidade": 1, "novas": 1, "texto": "t"}',
     {"motivo": "cv_indisponivel", "cv": None, "limite": "25%", "quantidade": 1, "sugeridas": 1,
      "texto": "t"}),
    ('{"aprovada": true, "motivo": "", "cv": "0.1"}', None),
    ("null", None),
    ('"lixo"', None),
])
def test_item_diz_quando_a_automatica_segurou_sugestoes_pelo_cv(api, emissor, banco, gravado, esperado):
    banco.respostas[("GET", "pesquisas_preco")] = [_bruto(_PESQUISA_MINIMA)]
    banco.respostas[("GET", "pesquisa_preco_itens")] = [_bruto("[" + _ITEM_MINIMO % (ITEM, gravado) + "]")]
    r = api().get(f"/api/v1/precos/pesquisas/{PESQUISA}", headers=_auth(emissor))
    assert r.status_code == 200, r.text
    assert r.json()["itens"][0]["revisao_cv"] == esperado
    # só o pedaço da memória que a tela usa viaja na consulta
    assert "barreira_cv:estatisticas->barreira_cv" in banco.chamadas[-1].url.params["select"]


# ---------------------------------------------------------------------------
# Lista: propostas e pendências (cotação multiportal, 10/11/2026)
# ---------------------------------------------------------------------------
def test_lista_traz_a_pendencia_da_ultima_busca_e_a_proposta_apta(api, emissor, banco):
    banco.respostas[("GET", "pesquisas_preco")] = [_bruto(
        '[{"id": "%s", "nome": "P", "objeto": "", "estado": "in_review", "valor_global": null,'
        ' "data_base": null, "responsavel": "", "local_referencia": "", "processo_id": null,'
        ' "versao": 1, "criado_em": "x", "atualizado_em": "x"}]' % PESQUISA)]
    banco.respostas[("GET", "pesquisa_preco_itens")] = [_bruto(
        '[{"id": "a", "numero": 1, "descricao": "x", "unidade": "UN", "quantidade": 1,'
        ' "estado": "review", "preco_estimado": 10.0000, "justificativa": "",'
        ' "barreira_cv": {"aprovada": true}, "pendencias": []},'
        ' {"id": "b", "numero": 2, "descricao": "y", "unidade": "UN", "quantidade": 1,'
        ' "estado": "review", "preco_estimado": 10.0000, "justificativa": "",'
        ' "pendencias": ["discrepante"]},'
        ' {"id": "c", "numero": 3, "descricao": "z", "unidade": "UN", "quantidade": 1,'
        ' "estado": "incomplete", "preco_estimado": null, "justificativa": ""}]')]
    banco.responder("GET", "pesquisa_preco_eventos", 200, [
        {"item_id": "c", "criado_em": "2026-11-10T10:00:00+00:00", "desfecho": "falha_tecnica"},
        {"item_id": "c", "criado_em": "2026-11-10T11:00:00+00:00", "desfecho": "amostra_insuficiente"},
        {"item_id": "a", "criado_em": "2026-11-10T11:00:00+00:00", "desfecho": "pronto_para_revisao"},
        {"item_id": "b", "criado_em": "2026-11-10T11:00:00+00:00", "desfecho": "<script>"},
    ])
    itens = {i["id"]: i for i in
             api().get(f"/api/v1/precos/pesquisas/{PESQUISA}", headers=_auth(emissor)).json()["itens"]}
    assert (itens["a"]["pendencia"], itens["a"]["apta"]) == ("pronto_para_revisao", True)
    # pendência de análise crítica: não é apta; desfecho desconhecido não passa
    assert (itens["b"]["pendencia"], itens["b"]["apta"]) == ("", False)
    # vale a busca MAIS RECENTE
    assert (itens["c"]["pendencia"], itens["c"]["apta"]) == ("amostra_insuficiente", False)


# ---------------------------------------------------------------------------
# Paginação e filtros no banco (pacote de 14/11/2026, RF-06/RF-07/RF-08)
# ---------------------------------------------------------------------------
URL_REFS = f"/api/v1/precos/pesquisas/{PESQUISA}/itens/{ITEM}/referencias"
UMA_REF = """{"id": "r1", "fonte_id": "pncp", "fonte_nome": "PNCP", "fonte_tipo": "sistema_oficial",
  "natureza_valor": "homologado", "status": "selected", "descricao_original": "Luva",
  "valor_unitario_original": 2.30, "valor_unitario_normalizado": 2.30, "uf": "PA",
  "coletado_em": "2026-10-20T10:00:00+00:00", "motivos": [], "bruto": {}}"""


def _pagina(banco, *, content_range="0-19/1000", status=206):
    banco.respostas[("GET", "pesquisa_preco_itens")] = [_bruto('[{"id": "%s"}]' % ITEM)]
    banco.respostas[("GET", "pesquisa_preco_referencias")] = [httpx.Response(
        status, content=f"[{UMA_REF}]".encode(),
        headers={"content-type": "application/json", "content-range": content_range})]


def test_pagina_20_e_total_do_conjunto_filtrado(api, emissor, banco):
    _pagina(banco)
    r = api().get(URL_REFS, params={"pagina": 3}, headers=_auth(emissor))
    assert r.status_code == 200, r.text
    assert r.headers["x-total-count"] == "1000"
    chamada = banco.chamadas[-1]
    params = chamada.url.params
    assert params["limit"] == "20" and params["offset"] == "40"
    assert params["order"] == "valor_unitario_normalizado.asc.nullslast,id.asc"   # desempate pelo id
    assert chamada.headers["prefer"] == "count=exact"
    assert params["tenant_id"].startswith("eq.") and params["item_id"] == f"eq.{ITEM}"


@pytest.mark.parametrize("tamanho", [1, 30, 100, 500])
def test_tamanho_fora_de_10_20_50_e_422(api, emissor, banco, tamanho):
    _pagina(banco)
    r = api().get(URL_REFS, params={"pagina": 1, "por_pagina": tamanho}, headers=_auth(emissor))
    assert r.status_code == 422


def test_filtros_vao_ao_banco_antes_da_paginacao(api, emissor, banco):
    _pagina(banco, content_range="0-0/1")
    r = api().get(URL_REFS, params={
        "pagina": 1, "por_pagina": 50, "situacao": "cesta", "fonte": "pncp", "uf": "pa",
        "preco_min": "1.50", "preco_max": "3", "desde": "2026-01-01", "ate": "2026-10-31",
        "q": "luva*,(nitrílica)", "ordem": "data_desc"}, headers=_auth(emissor))
    assert r.status_code == 200, r.text
    pares = banco.chamadas[-1].url.params.multi_items()
    assert ("status", "in.(selected,warning)") in pares
    assert ("fonte_id", "eq.pncp") in pares and ("uf", "eq.PA") in pares
    assert ("valor_unitario_normalizado", "gte.1.50") in pares
    assert ("valor_unitario_normalizado", "lte.3") in pares
    assert ("and", "(or(data_compra.gte.2026-01-01,data_resultado.gte.2026-01-01),"
                   "or(data_compra.lte.2026-10-31,data_resultado.lte.2026-10-31))") in pares
    # texto livre sem curinga nem sintaxe do PostgREST
    assert ("descricao_original", "ilike.*luva*") in pares
    assert ("descricao_original", "ilike.*nitrílica*") in pares
    assert dict(pares)["limit"] == "50"


@pytest.mark.parametrize("params", [
    {"preco_min": "5", "preco_max": "1"}, {"desde": "2026-10-01", "ate": "2026-01-01"},
    {"uf": "PAR"}, {"fonte": "pncp;drop"}, {"situacao": "todas"}, {"ordem": "id"}])
def test_filtro_invalido_e_422(api, emissor, banco, params):
    _pagina(banco)
    r = api().get(URL_REFS, params={"pagina": 1, **params}, headers=_auth(emissor))
    assert r.status_code == 422


def test_pagina_alem_do_fim_vem_vazia_com_o_total(api, emissor, banco):
    _pagina(banco, content_range="*/30", status=416)
    banco.respostas[("GET", "pesquisa_preco_referencias")][0]._content = b"[]"
    r = api().get(URL_REFS, params={"pagina": 9}, headers=_auth(emissor))
    assert r.status_code == 200 and r.json() == []
    assert r.headers["x-total-count"] == "30"


def test_sem_pagina_a_leitura_antiga_continua(api, emissor, banco):
    _pagina(banco, content_range="0-0/1", status=200)
    r = api().get(URL_REFS, headers=_auth(emissor))
    assert r.status_code == 200 and len(r.json()) == 1
    params = banco.chamadas[-1].url.params
    assert params["limit"] == "500" and "offset" not in params


def test_agregados_por_uf_fonte_e_cesta(api, emissor, banco):
    banco.respostas[("GET", "pesquisa_preco_itens")] = [_bruto('[{"id": "%s"}]' % ITEM)]
    banco.respostas[("GET", "pesquisa_preco_referencias")] = [_bruto("""[
      {"status": "selected", "fonte_id": "pncp", "fonte_nome": "PNCP", "uf": "PA", "valor_unitario_normalizado": 2.30},
      {"status": "warning", "fonte_id": "pncp", "fonte_nome": "PNCP", "uf": "pa", "valor_unitario_normalizado": 2.45},
      {"status": "candidate", "fonte_id": "cg", "fonte_nome": "Compras.gov.br", "uf": null, "valor_unitario_normalizado": null},
      {"status": "manual_review", "fonte_id": "cg", "fonte_nome": "Compras.gov.br", "uf": "SP", "valor_unitario_normalizado": 1.99}
    ]""")]
    r = api().get(f"{URL_REFS}/agregados", headers=_auth(emissor))
    assert r.status_code == 200, r.text
    a = r.json()
    assert (a["total"], a["na_cesta"], a["fora"], a["em_atencao"]) == (4, 2, 2, 2)
    assert a["ufs"] == [{"uf": "PA", "quantidade": 2}, {"uf": "SP", "quantidade": 1}]
    assert a["sem_uf"] == 1 and a["base_geografica"] == "uf_orgao" and a["metrica"] == "quantidade"
    assert a["preco_min"]["valor"] == "1.99" and a["preco_max"]["valor"] == "2.45"
    assert [f["id"] for f in a["fontes"]] == ["cg", "pncp"] or [f["quantidade"] for f in a["fontes"]] == [2, 2]
    assert "bruto" not in banco.chamadas[-1].url.params["select"]
