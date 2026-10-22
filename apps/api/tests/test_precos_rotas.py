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
