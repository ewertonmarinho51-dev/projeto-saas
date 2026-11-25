"""
`/api/v1/precos/referencias/seop` — custo de referência da SEOP-PA.

O índice é substituído (`repo.buscar_seop`) e REGISTRA o que recebeu; as
regras da importação supervisionada têm prova própria em `tests/test_seop.py`.
O que se prova aqui: a flag (404 desligada, ilegível também), os filtros (422
fora da regra), o valor em texto exato, a página do PDF oficial na resposta e
índice fora como 503.
"""

import pytest
from fastapi.testclient import TestClient

from govconect_api.config import carregar
from govconect_api.main import criar_app
from govconect_api.verificador import VerificadorSupabase
from src import db, governanca
from src.precos import repositorio as repo
from src.precos import seop

from apoio_jwt import EMISSOR, Emissor, PostgrestFalso

URL = "/api/v1/precos/referencias/seop"
PDF = "https://seop.pa.gov.br/sites/default/files/plainha_padrao_outubro_2026.pdf"
LINHA = {
    "registro_id": "r1", "chave_linha": "2026-10:011450", "competencia": "2026-10",
    "item": "1.1", "codigo": "011450",
    "descricao": "Aluguel de andaime metálico tipo fachadeiro (incluindo montagem edesmontagem)",
    "unidade": "m2/mês", "valor": "30.280000", "grupo": "SERVIÇOS PRELIMINARES", "pagina": 1,
    "bdi": "SEM BDI", "desoneracao": "SEM DESONERAÇÃO", "arquivo_sha256": "62" * 32,
    "url_arquivo": PDF, "versao_parser": seop.VERSAO_PARSER, "vigente": True,
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

    monkeypatch.setattr(repo, "buscar_seop", buscar)
    monkeypatch.setattr(db, "flag_ativa",
                        lambda nome: nome == governanca.FLAG_REFERENCIA_SEOP_PA)
    return chamadas


def test_consulta_devolve_o_custo_com_a_pagina_do_pdf(emissor, indice):
    r = _api(emissor).get(URL, params={"termo": "andaime metálico"}, headers=_h(emissor))
    assert r.status_code == 200, r.text
    corpo = r.json()
    assert "art. 23, § 3º" in corpo["fundamento"]
    assert corpo["pagina_oficial"] == seop.URL_PAGINA
    [x] = corpo["referencias"]
    assert x["valor"] == {"valor": "30.280000", "exibicao": "R$ 30,28"}
    assert (x["codigo"], x["item"], x["unidade"], x["pagina"]) == ("011450", "1.1", "m2/mês", 1)
    assert x["url_verificacao"] == PDF + "#page=1" and x["pdf"] == PDF
    assert (x["bdi"], x["desoneracao"]) == ("SEM BDI", "SEM DESONERAÇÃO")
    assert x["natureza"] == "custo_referencia_engenharia"
    assert x["competencia_exibicao"] == "outubro/2026"
    [(termos, filtros)] = indice
    assert termos == ["metalico", "andaime"]
    assert filtros == {"codigo": None, "competencia": None, "limite": 50}


def test_por_codigo_vai_so_pelo_codigo(emissor, indice):
    r = _api(emissor).get(URL, params={"codigo": "011450", "competencia": "2026-10"},
                          headers=_h(emissor))
    assert r.status_code == 200, r.text
    [(termos, filtros)] = indice
    assert termos == [] and filtros["codigo"] == "011450"
    assert filtros["competencia"] == "2026-10"


def test_desligada_ou_ilegivel_e_404(emissor, monkeypatch):
    chamou = []
    monkeypatch.setattr(repo, "buscar_seop", lambda *a, **k: chamou.append(1) or [])
    monkeypatch.setattr(db, "flag_ativa", lambda nome: False)
    r = _api(emissor).get(URL, params={"termo": "andaime"}, headers=_h(emissor))
    assert r.status_code == 404 and r.json()["code"] == "MODULE_UNAVAILABLE"

    def quebrada(nome):
        raise db.ErroBanco("flags indisponíveis")

    monkeypatch.setattr(db, "flag_ativa", quebrada)
    assert _api(emissor).get(URL, params={"termo": "andaime"},
                             headers=_h(emissor)).status_code == 404
    assert chamou == []


def test_modulo_de_precos_desligado_e_sem_token(emissor, indice):
    assert _api(emissor, precos=False).get(URL, headers=_h(emissor)).status_code == 404
    assert _api(emissor).get(URL).status_code == 401
    assert indice == []


@pytest.mark.parametrize("params", [
    {"codigo": "11450"}, {"codigo": "01145A"}, {"competencia": "2026-13"},
    {"limite": 0}, {"limite": 201}, {"termo": "x" * 301},
])
def test_filtro_fora_da_regra_e_422_sem_ir_ao_indice(emissor, indice, params):
    r = _api(emissor).get(URL, params=params, headers=_h(emissor))
    assert r.status_code == 422, r.text
    assert indice == []


def test_indice_fora_e_503(emissor, monkeypatch):
    def fora(*a, **k):
        raise db.ErroBanco("índice fora")

    monkeypatch.setattr(repo, "buscar_seop", fora)
    monkeypatch.setattr(db, "flag_ativa",
                        lambda nome: nome == governanca.FLAG_REFERENCIA_SEOP_PA)
    r = _api(emissor).get(URL, params={"termo": "andaime"}, headers=_h(emissor))
    assert r.status_code == 503 and r.json()["code"] == "DATABASE_UNAVAILABLE"
