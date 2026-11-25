"""
`/api/v1/precos/referencias/cmed` — teto CMED de medicamentos.

O índice é substituído (`repo.buscar_cmed`) por linhas REAIS lidas da
amostra oficial pelo próprio importador, e REGISTRA o que recebeu; as regras
da CMED têm prova própria em `tests/test_cmed.py`. O que se prova aqui: a
flag (404 desligada, ilegível também, a do SINAPI não abre esta), os filtros
(422), que o teto sai pela regra do CAP na alíquota pedida, com a isenção e
a rastreabilidade inteiras, e que índice fora é 503.
"""

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from govconect_api.config import carregar
from govconect_api.main import criar_app
from govconect_api.verificador import VerificadorSupabase
from src import db, governanca
from src.precos import cmed
from src.precos import repositorio as repo

from apoio_jwt import EMISSOR, Emissor, PostgrestFalso

URL = "/api/v1/precos/referencias/cmed"
AMOSTRA = (Path(__file__).resolve().parents[3] / "tests" / "fixtures" / "fontes_precos"
           / "cmed_2026_11_09" / "lista_pmvg_20261109_111901662.xlsx")
ARQUIVO = cmed.PREFIXO_ARQUIVOS + AMOSTRA.name + "/@@download/file"
_ARMAZEM = cmed.ArmazemEmMemoria()
cmed.importar(_ARMAZEM, AMOSTRA, url=ARQUIVO)
LINHAS = {l["ggrem"]: l for l in _ARMAZEM.registros.values()}
ORENCIA_SC, BAYCUTEN = "505113100020505", "538912020009303"


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
        return [dict(LINHAS[ORENCIA_SC]), dict(LINHAS[BAYCUTEN])]

    monkeypatch.setattr(repo, "buscar_cmed", buscar)
    monkeypatch.setattr(db, "flag_ativa", lambda nome: nome == governanca.FLAG_REFERENCIA_CMED)
    return chamadas


def test_teto_sai_pela_regra_do_cap_na_aliquota_pedida(emissor, indice):
    r = _api(emissor).get(URL, params={"termo": "orencia baycuten", "aliquota": "18"},
                          headers=_h(emissor))
    assert r.status_code == 200, r.text
    corpo = r.json()
    assert corpo["publicada_em"] == "2026-11-09T17:30:00-03:00" and corpo["aliquota"] == "18"
    assert "CAP" in corpo["fundamento"] and "não entra na cesta" in corpo["fundamento"]
    assert corpo["pagina_oficial"] == cmed.URL_PAGINA
    cap, sem = corpo["tetos"]
    assert cap["teto_governo"] == {"valor": "6596.70", "exibicao": "R$ 6.596,70"}
    assert cap["pf"]["valor"] == "8224.28" and cap["pmvg"]["valor"] == "6596.70"
    assert cap["base_do_teto"] == "PMVG (CAP aplicado ao PF)"
    assert cap["isento_icms"] and cap["confaz87"] and not cap["icms_0"]
    assert cap["teto_governo_isento"]["valor"] == "5409.29"
    assert sem["teto_governo"]["valor"] == "37.48" and sem["pmvg"]["valor"] == "30.06"
    assert sem["base_do_teto"] == "PF (fora do CAP)" and not sem["isento_icms"]
    assert cap["rotulo_aliquota"] == "ICMS 18%" and cap["natureza"] == "teto_regulatorio"
    assert "não preço de compra" in cap["rotulo_natureza"]
    assert (cap["arquivo_url"], cap["arquivo"], cap["linha_planilha"]) == (
        ARQUIVO, AMOSTRA.name, 4)
    assert cap["eans"] == ["7896016808197"] and cap["ggrem"] == ORENCIA_SC
    [(termos, filtros)] = indice
    assert set(termos) == {"orencia", "baycuten"}
    assert filtros == {"codigo": None, "limite": 50}


def test_codigo_vai_sozinho(emissor, indice):
    r = _api(emissor).get(URL, params={"codigo": "7891106000956", "aliquota": "12_alc",
                                       "limite": 20}, headers=_h(emissor))
    assert r.status_code == 200, r.text
    assert r.json()["tetos"][1]["pf"]["valor"] == "31.18"
    assert indice == [([], {"codigo": "7891106000956", "limite": 20})]


@pytest.mark.parametrize("params", [
    {"codigo": "1234"}, {"codigo": "1" * 16}, {"codigo": "789110600095a"},
    {"aliquota": "19,5"}, {"aliquota": "pmc"}, {"limite": 0}, {"limite": 201},
    {"termo": "x" * 301},
])
def test_filtro_fora_da_regra_e_422_sem_ir_ao_indice(emissor, indice, params):
    r = _api(emissor).get(URL, params={"termo": "orencia", **params}, headers=_h(emissor))
    assert r.status_code == 422, r.text
    assert indice == []


def test_flag_desligada_ou_ilegivel_e_404(emissor, indice, monkeypatch):
    monkeypatch.setattr(db, "flag_ativa", lambda nome: nome == governanca.FLAG_REFERENCIA_SINAPI)
    assert _api(emissor).get(URL, params={"termo": "orencia"},
                             headers=_h(emissor)).status_code == 404

    def quebrada(nome):
        raise db.ErroBanco("flags indisponíveis")

    monkeypatch.setattr(db, "flag_ativa", quebrada)
    r = _api(emissor).get(URL, params={"termo": "orencia"}, headers=_h(emissor))
    assert r.status_code == 404 and r.json()["code"] == "MODULE_UNAVAILABLE"
    assert indice == []


def test_modulo_de_precos_desligado_e_404_e_sem_token_e_401(emissor, indice):
    assert _api(emissor, precos=False).get(URL, params={"termo": "orencia"},
                                           headers=_h(emissor)).status_code == 404
    assert _api(emissor).get(URL, params={"termo": "orencia"}).status_code == 401


def test_indice_fora_do_ar_e_503_com_recado(emissor, indice, monkeypatch):
    def fora(termos, **filtros):
        raise ConnectionError("banco fora")

    monkeypatch.setattr(repo, "buscar_cmed", fora)
    r = _api(emissor).get(URL, params={"termo": "orencia"}, headers=_h(emissor))
    assert r.status_code == 503 and r.json()["code"] == "SOURCE_UNAVAILABLE"
    assert "banco fora" not in r.text


def test_linha_fora_do_endereco_oficial_nao_chega_a_tela(emissor, indice, monkeypatch):
    monkeypatch.setattr(repo, "buscar_cmed", lambda termos, **f: [
        {**LINHAS[BAYCUTEN], "url_arquivo": "https://exemplo.com/x.xlsx"}])
    r = _api(emissor).get(URL, params={"termo": "orencia"}, headers=_h(emissor))
    assert r.status_code == 200 and r.json()["tetos"] == []
