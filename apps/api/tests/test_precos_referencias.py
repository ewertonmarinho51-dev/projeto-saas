"""
Consulta ao custo de referência do SINAPI pela API (23/11/2026).

O domínio (`sinapi.consultar`) tem prova própria em `tests/test_sinapi.py`.
Aqui a leitura do índice (`repo.buscar_indice_sinapi`) e a trava
(`consulta_aberta`) são substituídas. O que se prova: fechada por padrão é
404; os filtros chegam conferidos; dinheiro sai como string exata; a resposta
diz que aquilo não é preço de compra; banco fora é 503, não lista vazia.
"""

import pytest
from fastapi.testclient import TestClient

from govconect_api import precos_referencias
from govconect_api.config import carregar
from govconect_api.main import criar_app
from govconect_api.verificador import VerificadorSupabase
from src import db
from src.precos import fontes_externas
from src.precos import repositorio as repo

from apoio_jwt import EMISSOR, Emissor, PostgrestFalso

URL = "/api/v1/precos/referencias/sinapi"
CAIXA = "https://www.caixa.gov.br/Downloads/sinapi-relatorios-mensais/"
LINHA = {
    "registro_id": "r1", "chave_linha": "2026-10:PA:insumo:sem_desoneracao:1379",
    "competencia": "2026-10", "uf": "PA", "tipo": "insumo", "regime": "sem_desoneracao",
    "codigo": "1379", "descricao": "CIMENTO PORTLAND COMPOSTO CP II-32", "unidade": "KG",
    "valor": "1.080000", "classificacao": "MATERIAL", "origem_preco": "C",
    "percentual_sp": None, "aba": "ISD", "linha_planilha": 1169,
    "arquivo_sha256": "2e99cde7" + "0" * 56,
    "url_arquivo": CAIXA + "SINAPI-2026-10-formato-xlsx.zip", "versao_parser": "v",
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
        return [LINHA]

    monkeypatch.setattr(repo, "buscar_indice_sinapi", buscar)
    monkeypatch.setattr(precos_referencias, "consulta_aberta", lambda: True)
    return chamadas


def test_fechada_por_padrao_e_404(emissor, monkeypatch):
    # sem substituir a trava: licença não avaliada, nada abre
    monkeypatch.setattr(db, "flag_ativa", lambda nome: True)
    assert not fontes_externas.habilitada("sinapi")
    r = _api(emissor).get(URL, params={"termo": "cimento"}, headers=_h(emissor))
    assert r.status_code == 404


def test_modulo_de_precos_desligado_e_404_e_sem_token_e_401(emissor, indice):
    assert _api(emissor, precos=False).get(URL, headers=_h(emissor)).status_code == 404
    assert _api(emissor).get(URL).status_code == 401
    assert indice == []


def test_consulta_devolve_a_origem_e_a_natureza(emissor, indice):
    r = _api(emissor).get(URL, params={"termo": "Cimento Portland", "uf": "pa",
                                       "tipo": "insumo"}, headers=_h(emissor))
    assert r.status_code == 200, r.text
    corpo = r.json()
    assert "não é preço de compra" in corpo["aviso"].lower()
    [item] = corpo["itens"]
    # o valor exato do índice, em texto; a exibição arredonda ao centavo
    assert item["valor"] == {"valor": "1.080000", "exibicao": "R$ 1,08"}
    assert (item["codigo"], item["unidade"], item["uf"]) == ("1379", "KG", "PA")
    assert (item["competencia_exibicao"], item["rotulo_regime"]) == ("10/2026", "sem desoneração")
    assert item["natureza"] == "custo_referencia_engenharia"
    assert item["rotulo_origem"] == "coletado"
    assert item["url_verificacao"] == CAIXA + "SINAPI-2026-10-formato-xlsx.zip"
    assert (item["aba"], item["linha_planilha"]) == ("ISD", 1169)
    [(termos, filtros)] = indice
    assert termos == ["portland", "cimento"]
    assert filtros == {"codigo": None, "uf": "PA", "competencia": None, "tipo": "insumo",
                       "regime": "sem_desoneracao", "limite": 50}


def test_por_codigo_vai_so_pelo_codigo(emissor, indice):
    r = _api(emissor).get(URL, params={"codigo": "104658", "regime": "com_desoneracao",
                                       "competencia": "2026-09"}, headers=_h(emissor))
    assert r.status_code == 200, r.text
    [(termos, filtros)] = indice
    assert termos == [] and filtros["codigo"] == "104658"
    assert (filtros["regime"], filtros["competencia"]) == ("com_desoneracao", "2026-09")


@pytest.mark.parametrize("params", [
    {"codigo": "10465A"}, {"competencia": "2026-13"}, {"competencia": "202610"},
    {"tipo": "servico"}, {"regime": "desonerado"}, {"uf": "XX", "termo": "cimento"},
    {"limite": 0}, {"limite": 201}, {"termo": "x" * 201},
])
def test_filtro_fora_da_regra_e_422_e_nao_chega_ao_indice(emissor, indice, params):
    r = _api(emissor).get(URL, params=params, headers=_h(emissor))
    assert r.status_code == 422, r.text
    assert indice == []


def test_banco_fora_e_503_nao_lista_vazia(emissor, monkeypatch):
    def fora(termos, **filtros):
        raise db.ErroBanco("índice fora")

    monkeypatch.setattr(repo, "buscar_indice_sinapi", fora)
    monkeypatch.setattr(precos_referencias, "consulta_aberta", lambda: True)
    r = _api(emissor).get(URL, params={"termo": "cimento"}, headers=_h(emissor))
    assert r.status_code == 503 and r.json()["code"] == "DATABASE_UNAVAILABLE"


def test_sem_termo_nem_codigo_nao_consulta(emissor, indice):
    r = _api(emissor).get(URL, params={"termo": "de a"}, headers=_h(emissor))
    assert r.status_code == 200 and r.json()["itens"] == [] and indice == []
