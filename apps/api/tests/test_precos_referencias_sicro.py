"""
`/api/v1/precos/referencias/sicro` — custo referencial do SICRO (DNIT).

O índice é substituído (`repo.buscar_sicro`) e REGISTRA o que recebeu; as
regras do SICRO têm prova própria em `tests/test_sicro.py`. O que se prova
aqui: a flag (404 desligada, ilegível também, a do SINAPI não abre esta),
os filtros (422 fora da regra), que o valor sai exato com as casas que o DNIT
publica, que a rastreabilidade chega inteira e que índice fora é 503.
"""

import pytest
from fastapi.testclient import TestClient

from govconect_api.config import carregar
from govconect_api.main import criar_app
from govconect_api.verificador import VerificadorSupabase
from src import db, governanca
from src.precos import repositorio as repo
from src.precos import sicro

from apoio_jwt import EMISSOR, Emissor, PostgrestFalso

URL = "/api/v1/precos/referencias/sicro"
ARQUIVO = sicro.URL_RELATORIOS + "norte/para/2026/julho/pa-07-2026.7z"
BASE = {
    "chave_linha": "c", "competencia": "2026-07", "uf": "PA", "arquivo_sha256": "3a" * 32,
    "vigente": True, "url_arquivo": ARQUIVO, "arquivo": "pa-07-2026.7z", "hash_linha": "h",
    "versao_parser": sicro.VERSAO_PARSER, "valor_improdutivo": None, "origem_preco": None,
}
EQUIPAMENTO = {**BASE, "registro_id": "e" * 40, "tipo": "equipamento",
               "regime": "sem_desoneracao", "codigo": "E9009",
               "descricao": "Embarcação rebocadora - 268 kW", "descricao_busca": "x",
               "unidade": "h", "valor": "489.8398", "valor_improdutivo": "149.9339",
               "origem_preco": "PRE",
               "planilha": "PA 07-2026 Relatório Sintético de Equipamentos.xlsx",
               "linha_planilha": 10}
COMPOSICAO = {**BASE, "registro_id": "c" * 40, "tipo": "composicao",
              "regime": "sem_desoneracao", "codigo": "0308313",
              "descricao": "Aparelho de apoio metálico", "descricao_busca": "x",
              "unidade": "un", "valor": "31434.19",
              "planilha": "PA 07-2026 Relatório Sintético de Composições de Custos.xlsx",
              "linha_planilha": 5}


@pytest.fixture
def emissor():
    return Emissor()


def _api(emissor, precos=True):
    config = carregar({"APP_ENV": "test", "SUPABASE_URL": "https://exemplo-staging.supabase.co",
                       "SUPABASE_KEY": "chave-publicavel-de-teste",
                       "PRICE_RESEARCH_ENABLED": "1" if precos else "0"})
    rest = PostgrestFalso().cliente()
    return TestClient(criar_app(config, rest=rest, verificador=VerificadorSupabase(
        emissor=EMISSOR, rest=rest, chave_para=emissor.chave_para)), raise_server_exceptions=False)


def _h(emissor):
    return {"Authorization": f"Bearer {emissor.token()}"}


@pytest.fixture
def indice(monkeypatch):
    chamadas: list = []

    def buscar(termos, **filtros):
        chamadas.append((termos, filtros))
        return [dict(EQUIPAMENTO), dict(COMPOSICAO)]

    monkeypatch.setattr(repo, "buscar_sicro", buscar)
    monkeypatch.setattr(db, "flag_ativa",
                        lambda nome: nome == governanca.FLAG_REFERENCIA_SICRO)
    return chamadas


def test_consulta_por_codigo_devolve_custo_rastreavel_com_as_casas_do_dnit(emissor, indice):
    r = _api(emissor).get(URL, params={"codigo": "e9009", "uf": "pa"}, headers=_h(emissor))
    assert r.status_code == 200, r.text
    corpo = r.json()
    assert corpo["competencia"] == "2026-07"
    assert "SICRO" in corpo["fundamento"] and "§ 3º" in corpo["fundamento"]
    assert "sem desoneração" in corpo["fundamento"]
    assert corpo["pagina_oficial"] == sicro.URL_PAGINA
    equipamento, composicao = corpo["referencias"]
    assert equipamento["valor"] == {"valor": "489.8398", "exibicao": "R$ 489,8398"}
    assert equipamento["valor_improdutivo"] == {"valor": "149.9339", "exibicao": "R$ 149,9339"}
    assert (equipamento["rotulo_tipo"], equipamento["origem_preco"],
            equipamento["rotulo_origem"]) == ("Equipamento", "PRE", "preço referencial estimado")
    assert equipamento["natureza"] == "custo_referencial"
    assert equipamento["rotulo_regime"] == "encargos sociais sem desoneração"
    assert equipamento["identificacao"] == "SICRO Equipamento E9009 — PA 07/2026"
    assert (equipamento["arquivo"], equipamento["arquivo_url"]) == ("pa-07-2026.7z", ARQUIVO)
    assert (equipamento["planilha"], equipamento["linha_planilha"]) == (
        "PA 07-2026 Relatório Sintético de Equipamentos.xlsx", 10)
    # composição em centavos, com milhar
    assert composicao["valor"] == {"valor": "31434.19", "exibicao": "R$ 31.434,19"}
    assert composicao["valor_improdutivo"] is None
    [(termos, filtros)] = indice
    assert termos == [] and filtros == {"codigo": "E9009", "uf": "PA", "competencia": None,
                                        "regime": "sem_desoneracao", "tipo": None, "limite": 50}


def test_consulta_por_termo_com_filtros(emissor, indice):
    r = _api(emissor).get(URL, params={
        "termo": "concreto usinado", "regime": "com_desoneracao", "tipo": "material",
        "competencia": "2026-07", "limite": 20}, headers=_h(emissor))
    assert r.status_code == 200, r.text
    [(termos, filtros)] = indice
    assert set(termos) == {"concreto", "usinado"}
    assert filtros == {"codigo": None, "uf": "PA", "competencia": "2026-07",
                       "regime": "com_desoneracao", "tipo": "material", "limite": 20}


@pytest.mark.parametrize("params", [
    {"codigo": "110605"}, {"codigo": "X0004"}, {"codigo": "M00045"}, {"uf": "XX"},
    {"competencia": "2026-13"}, {"regime": "nao_se_aplica"}, {"regime": "sem_encargos"},
    {"tipo": "servico"}, {"limite": 0}, {"limite": 201}, {"termo": "x" * 301},
])
def test_filtro_fora_da_regra_e_422_sem_ir_ao_indice(emissor, indice, params):
    r = _api(emissor).get(URL, params={"termo": "concreto", **params}, headers=_h(emissor))
    assert r.status_code == 422, r.text
    assert indice == []


def test_flag_desligada_ou_ilegivel_e_404(emissor, indice, monkeypatch):
    monkeypatch.setattr(db, "flag_ativa", lambda nome: nome == governanca.FLAG_REFERENCIA_SINAPI)
    assert _api(emissor).get(URL, params={"termo": "concreto"}, headers=_h(emissor)).status_code == 404

    def quebrada(nome):
        raise db.ErroBanco("flags indisponíveis")

    monkeypatch.setattr(db, "flag_ativa", quebrada)
    r = _api(emissor).get(URL, params={"termo": "concreto"}, headers=_h(emissor))
    assert r.status_code == 404 and r.json()["code"] == "MODULE_UNAVAILABLE"
    assert indice == []


def test_modulo_de_precos_desligado_e_404_e_sem_token_e_401(emissor, indice):
    assert _api(emissor, precos=False).get(URL, params={"termo": "concreto"},
                                           headers=_h(emissor)).status_code == 404
    assert _api(emissor).get(URL, params={"termo": "concreto"}).status_code == 401


def test_indice_fora_do_ar_e_503_com_recado(emissor, indice, monkeypatch):
    def fora(termos, **filtros):
        raise ConnectionError("banco fora")

    monkeypatch.setattr(repo, "buscar_sicro", fora)
    r = _api(emissor).get(URL, params={"termo": "concreto"}, headers=_h(emissor))
    assert r.status_code == 503 and r.json()["code"] == "SOURCE_UNAVAILABLE"
    assert "banco fora" not in r.text


def test_linha_fora_do_endereco_oficial_nao_chega_a_tela(emissor, indice, monkeypatch):
    monkeypatch.setattr(repo, "buscar_sicro", lambda termos, **f: [
        {**EQUIPAMENTO, "url_arquivo": "https://exemplo.com/pa-07-2026.7z"},
        {**COMPOSICAO, "valor": "0"}])
    r = _api(emissor).get(URL, params={"termo": "concreto"}, headers=_h(emissor))
    assert r.status_code == 200 and r.json()["referencias"] == []
