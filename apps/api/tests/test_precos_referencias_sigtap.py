"""
`/api/v1/precos/referencias/sigtap` — remuneração da Tabela Unificada do SUS.

O índice é substituído (`repo.buscar_sigtap`) e REGISTRA o que recebeu; as
regras do SIGTAP têm prova própria em `tests/test_sigtap.py`. O que se prova
aqui: a flag (404 desligada, ilegível também), os filtros (422 fora da
regra), que os valores saem em texto exato com os totais ambulatorial (SA) e
hospitalar (SH + SP) e a natureza "remuneracao_sus", que a rastreabilidade
chega inteira e que índice fora é 503 com recado.
"""

import pytest
from fastapi.testclient import TestClient

from govconect_api.config import carregar
from govconect_api.main import criar_app
from govconect_api.verificador import VerificadorSupabase
from src import db, governanca
from src.precos import repositorio as repo
from src.precos import sigtap

from apoio_jwt import EMISSOR, Emissor, PostgrestFalso

URL = "/api/v1/precos/referencias/sigtap"
ARQUIVO = "TabelaUnificada_202611_v2611051737.zip"
LINHA = {
    "registro_id": "ab" * 20, "chave_linha": "2026-11:0411010034",
    "competencia": "2026-11", "arquivo_sha256": "06" * 32, "vigente": True,
    "codigo": "0411010034", "nome": "PARTO CESARIANO",
    "nome_busca": "parto cesariano", "complexidade": "2", "sexo": "F",
    "valor_sa": "0.00", "valor_sh": "395.68", "valor_sp": "150.05",
    "financiamento": "MEDIA E ALTA COMPLEXIDADE (MAC)", "rubrica": None,
    "modalidades": ["Hospitalar"], "grupo": "Procedimentos cirúrgicos",
    "subgrupo": "Obstetrícia", "forma_organizacao": "Parto e nascimento",
    "linha_arquivo": 3526, "arquivo": ARQUIVO, "hash_linha": "h",
    "versao_parser": sigtap.VERSAO_PARSER,
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

    monkeypatch.setattr(repo, "buscar_sigtap", buscar)
    monkeypatch.setattr(db, "flag_ativa",
                        lambda nome: nome == governanca.FLAG_REFERENCIA_SIGTAP)
    return chamadas


def test_consulta_por_codigo_devolve_remuneracao_rastreavel(emissor, indice):
    r = _api(emissor).get(URL, params={"codigo": "0411010034"}, headers=_h(emissor))
    assert r.status_code == 200, r.text
    corpo = r.json()
    assert corpo["competencia"] == "2026-11"
    assert "SH + SP" in corpo["fundamento"] and "não entra na cesta" in corpo["fundamento"]
    assert corpo["pagina_oficial"] == sigtap.URL_PAGINA
    [p] = corpo["procedimentos"]
    assert p["codigo_formatado"] == "04.11.01.003-4"
    assert p["valor_sh"] == {"valor": "395.68", "exibicao": "R$ 395,68"}
    assert p["valor_sp"] == {"valor": "150.05", "exibicao": "R$ 150,05"}
    assert p["total_hospitalar"] == {"valor": "545.73", "exibicao": "R$ 545,73"}
    assert p["total_ambulatorial"]["valor"] == "0.00" and p["sem_valor"] is False
    assert p["natureza"] == "remuneracao_sus"
    assert "não preço de compra" in p["rotulo_natureza"]
    assert p["modalidades"] == ["Hospitalar"] and p["competencia_exibicao"] == "11/2026"
    assert p["arquivo_url"] == f"ftp://ftp2.datasus.gov.br/pub/sistemas/tup/downloads/{ARQUIVO}"
    assert (p["arquivo"], p["linha_arquivo"], p["arquivo_sha256"]) == (ARQUIVO, 3526, "06" * 32)
    # o código vai sozinho, sem termos
    [(termos, filtros)] = indice
    assert termos == [] and filtros == {"codigo": "0411010034", "competencia": None,
                                        "modalidade": None, "limite": 50}


def test_consulta_por_termo_com_filtros(emissor, indice):
    r = _api(emissor).get(URL, params={
        "termo": "parto cesariano", "modalidade": "Hospitalar",
        "competencia": "2026-11", "limite": 20}, headers=_h(emissor))
    assert r.status_code == 200, r.text
    [(termos, filtros)] = indice
    assert set(termos) == {"parto", "cesariano"}
    assert filtros == {"codigo": None, "competencia": "2026-11",
                       "modalidade": "Hospitalar", "limite": 20}


@pytest.mark.parametrize("params", [
    {"codigo": "041101003"}, {"codigo": "04.11.01.003-4"}, {"codigo": "041101003a"},
    {"competencia": "2026-13"}, {"competencia": "11/2026"}, {"modalidade": "Outra"},
    {"limite": 0}, {"limite": 201}, {"termo": "x" * 301},
])
def test_filtro_fora_da_regra_e_422_sem_ir_ao_indice(emissor, indice, params):
    r = _api(emissor).get(URL, params={"termo": "parto", **params}, headers=_h(emissor))
    assert r.status_code == 422, r.text
    assert indice == []


def test_flag_desligada_ou_ilegivel_e_404(emissor, indice, monkeypatch):
    monkeypatch.setattr(db, "flag_ativa", lambda nome: False)
    assert _api(emissor).get(URL, params={"termo": "parto"}, headers=_h(emissor)).status_code == 404
    # a flag do SINAPI ligada não abre o SIGTAP
    monkeypatch.setattr(db, "flag_ativa",
                        lambda nome: nome == governanca.FLAG_REFERENCIA_SINAPI)
    assert _api(emissor).get(URL, params={"termo": "parto"}, headers=_h(emissor)).status_code == 404

    def quebrada(nome):
        raise db.ErroBanco("flags indisponíveis")

    monkeypatch.setattr(db, "flag_ativa", quebrada)
    r = _api(emissor).get(URL, params={"termo": "parto"}, headers=_h(emissor))
    assert r.status_code == 404 and r.json()["code"] == "MODULE_UNAVAILABLE"
    assert indice == []


def test_modulo_de_precos_desligado_e_404_e_sem_token_e_401(emissor, indice):
    assert _api(emissor, precos=False).get(URL, params={"termo": "parto"},
                                           headers=_h(emissor)).status_code == 404
    assert _api(emissor).get(URL, params={"termo": "parto"}).status_code == 401


def test_indice_fora_do_ar_e_503_com_recado(emissor, indice, monkeypatch):
    def fora(termos, **filtros):
        raise ConnectionError("banco fora")

    monkeypatch.setattr(repo, "buscar_sigtap", fora)
    r = _api(emissor).get(URL, params={"termo": "parto"}, headers=_h(emissor))
    assert r.status_code == 503 and r.json()["code"] == "SOURCE_UNAVAILABLE"
    assert "banco fora" not in r.text


def test_linha_sem_rastreabilidade_ou_com_valor_fora_nao_chega_a_tela(emissor, indice, monkeypatch):
    monkeypatch.setattr(repo, "buscar_sigtap", lambda termos, **f: [
        {**LINHA, "arquivo": "outro.zip"},
        {**LINHA, "registro_id": "x", "valor_sh": "-1.00"},
        {**LINHA, "registro_id": "y", "codigo": "123"}])
    r = _api(emissor).get(URL, params={"termo": "parto"}, headers=_h(emissor))
    assert r.status_code == 200 and r.json()["procedimentos"] == []
