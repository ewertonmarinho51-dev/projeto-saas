"""
`/api/v1/precos/referencias/sinapi` — custo referencial de engenharia.

O índice é substituído (`repo.buscar_sinapi`) e REGISTRA o que recebeu; as
regras do SINAPI têm prova própria em `tests/test_sinapi.py`. O que se
prova aqui: a flag (404 desligada, ilegível também), os filtros (422 fora
da regra), que o valor sai em texto exato com a natureza "custo_referencial",
que a rastreabilidade chega inteira e que índice fora é 503 com recado.
"""

import pytest
from fastapi.testclient import TestClient

from govconect_api.config import carregar
from govconect_api.main import criar_app
from govconect_api.verificador import VerificadorSupabase
from src import db, governanca
from src.precos import repositorio as repo
from src.precos import sinapi

from apoio_jwt import EMISSOR, Emissor, PostgrestFalso

URL = "/api/v1/precos/referencias/sinapi"
LINHA = {
    "registro_id": "sinapi:2026-10:composicao:104658:PA:sem_desoneracao",
    "competencia": "2026-10", "arquivo_sha256": "2e" * 32, "vigente": True,
    "tipo": "composicao", "regime": "sem_desoneracao", "codigo": "104658",
    "descricao": "PISO PODOTÁTIL DE ALERTA OU DIRECIONAL, DE CONCRETO, ASSENTADO SOBRE "
                 "ARGAMASSA. AF_03/2024",
    "descricao_busca": "piso podotatil", "unidade": "M2", "uf": "PA",
    "valor": 189.32, "classificacao": "Acessibilidade", "origem_preco": None,
    "percentual_sp": 0.0011, "aba": "CSD", "linha_planilha": 11,
    "url_arquivo": sinapi.url_da_competencia("2026-10"), "hash_linha": "h",
    "versao_parser": sinapi.VERSAO_PARSER,
}


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
        return [dict(LINHA)]

    monkeypatch.setattr(repo, "buscar_sinapi", buscar)
    monkeypatch.setattr(db, "flag_ativa",
                        lambda nome: nome == governanca.FLAG_REFERENCIA_SINAPI)
    return chamadas


def test_consulta_por_codigo_devolve_custo_referencial_rastreavel(emissor, indice):
    r = _api(emissor).get(URL, params={"codigo": "104658", "uf": "pa"}, headers=_h(emissor))
    assert r.status_code == 200, r.text
    corpo = r.json()
    assert corpo["competencia"] == "2026-10"
    assert "art. 23, § 2º, I" in corpo["fundamento"] and "§ 3º" in corpo["fundamento"]
    assert corpo["pagina_oficial"].startswith("https://www.caixa.gov.br/")
    [ref] = corpo["referencias"]
    assert ref["valor"] == {"valor": "189.32", "exibicao": "R$ 189,32"}
    assert ref["natureza"] == "custo_referencial"
    assert (ref["tipo"], ref["codigo"], ref["uf"], ref["unidade"]) == (
        "composicao", "104658", "PA", "M2")
    assert ref["regime"] == "sem_desoneracao"
    assert ref["rotulo_regime"] == "encargos sociais sem desoneração"
    assert ref["percentual_sp"] == "0.0011" and ref["origem_preco"] is None
    assert ref["planilha"] == sinapi.url_da_competencia("2026-10")
    assert (ref["aba"], ref["linha_planilha"]) == ("CSD", 11)
    assert ref["identificacao"] == "SINAPI Composição 104658 — PA 10/2026"
    # o código vai sozinho, com a UF em maiúsculas e o regime padrão
    [(termos, filtros)] = indice
    assert termos == [] and filtros["codigo"] == "104658" and filtros["uf"] == "PA"
    assert filtros["regime"] == "sem_desoneracao" and filtros["competencia"] is None


def test_consulta_por_termo_com_filtros(emissor, indice):
    r = _api(emissor).get(URL, params={
        "termo": "piso podotátil", "regime": "com_desoneracao", "tipo": "composicao",
        "competencia": "2026-10", "limite": 20}, headers=_h(emissor))
    assert r.status_code == 200, r.text
    [(termos, filtros)] = indice
    assert set(termos) == {"piso", "podotatil"}
    assert filtros == {"codigo": None, "uf": "PA", "competencia": "2026-10",
                       "regime": "com_desoneracao", "tipo": "composicao", "limite": 20}


@pytest.mark.parametrize("params", [
    {"codigo": "104658a"}, {"codigo": "1" * 10}, {"uf": "XX"}, {"uf": "P"},
    {"competencia": "2026-13"}, {"competencia": "10/2026"}, {"regime": "outro"},
    {"tipo": "servico"}, {"limite": 0}, {"limite": 201}, {"termo": "x" * 301},
])
def test_filtro_fora_da_regra_e_422_sem_ir_ao_indice(emissor, indice, params):
    r = _api(emissor).get(URL, params={"termo": "piso", **params}, headers=_h(emissor))
    assert r.status_code == 422, r.text
    assert indice == []


def test_flag_desligada_ou_ilegivel_e_404(emissor, indice, monkeypatch):
    monkeypatch.setattr(db, "flag_ativa", lambda nome: False)
    assert _api(emissor).get(URL, params={"termo": "piso"}, headers=_h(emissor)).status_code == 404

    def quebrada(nome):
        raise db.ErroBanco("flags indisponíveis")

    monkeypatch.setattr(db, "flag_ativa", quebrada)
    r = _api(emissor).get(URL, params={"termo": "piso"}, headers=_h(emissor))
    assert r.status_code == 404 and r.json()["code"] == "MODULE_UNAVAILABLE"
    assert indice == []


def test_modulo_de_precos_desligado_e_404_e_sem_token_e_401(emissor, indice):
    assert _api(emissor, precos=False).get(URL, params={"termo": "piso"},
                                           headers=_h(emissor)).status_code == 404
    assert _api(emissor).get(URL, params={"termo": "piso"}).status_code == 401


def test_indice_fora_do_ar_e_503_com_recado(emissor, indice, monkeypatch):
    def fora(termos, **filtros):
        raise ConnectionError("banco fora")

    monkeypatch.setattr(repo, "buscar_sinapi", fora)
    r = _api(emissor).get(URL, params={"termo": "piso"}, headers=_h(emissor))
    assert r.status_code == 503 and r.json()["code"] == "SOURCE_UNAVAILABLE"
    assert "banco fora" not in r.text


def test_linha_fora_do_endereco_oficial_nao_chega_a_tela(emissor, indice, monkeypatch):
    monkeypatch.setattr(repo, "buscar_sinapi", lambda termos, **f: [
        {**LINHA, "url_arquivo": "https://exemplo.com/sinapi.zip"},
        {**LINHA, "registro_id": "x", "valor": 0}])
    r = _api(emissor).get(URL, params={"termo": "piso"}, headers=_h(emissor))
    assert r.status_code == 200 and r.json()["referencias"] == []
