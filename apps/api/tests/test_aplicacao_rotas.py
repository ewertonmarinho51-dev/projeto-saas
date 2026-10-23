"""
Aplicar a pesquisa ao processo pela API (P04f).

Domínio de aplicação VERDADEIRO (casamento, diff, planilha.calcular,
cascata dos documentos); PostgREST simulado. O que se prova: a prévia
mostra o antes/depois e os documentos que caem; a aplicação exige a
confirmação do descarte e a versão vista do processo (compare-and-set);
só dono (ou admin) da pesquisa E do processo; dinheiro sai como string.
"""

import pytest
from fastapi.testclient import TestClient

from govconect_api.config import carregar
from govconect_api.main import criar_app
from govconect_api.verificador import VerificadorSupabase
from src.precos import relatorio
from src.precos import repositorio as repo

from apoio_jwt import EMISSOR, TENANT_A, USUARIO_A, Emissor, PostgrestFalso

P = "f0f0f0f0-0000-4000-8000-000000000001"
PROC = "f0f0f0f0-0000-4000-8000-0000000000aa"
OUTRO = "99999999-0000-4000-8000-000000000009"
VERSAO = "2026-10-23T10:00:00.000001+00:00"
URL = f"/api/v1/precos/pesquisas/{P}/aplicacao"


def _processo(dono=USUARIO_A, documentos=None, aprovados=None):
    return {"id": PROC, "auth_user_id": dono, "atualizado_em": VERSAO,
            "dados": {"objeto": "Aquisição", "valor_estimado": 300.0,
                      "itens": [{"codigo": "451234", "descricao": "Caneta esferográfica azul",
                                 "unidade": "UN", "quantidade": 150, "valor_unitario": 2.0}]},
            "documentos": documentos if documentos is not None else {"dfd": "texto", "etp": "texto"},
            "aprovados": aprovados if aprovados is not None else ["dfd"]}


@pytest.fixture
def emissor():
    return Emissor()


@pytest.fixture
def dominio(monkeypatch):
    estado = {"pesquisa": {"id": P, "tenant_id": TENANT_A, "estado": "completed",
                           "processo_id": PROC, "nome": "Pesquisa", "versao": 1},
              "movidas": [], "eventos": []}
    item = {"id": "i1", "numero": 1, "codigo": "451234", "descricao": "Caneta esferográfica azul",
            "unidade": "UN", "quantidade": "150", "estado": "complete",
            "preco_estimado": "2.3450", "preco_total": "351.7500"}
    monkeypatch.setattr(repo, "obter_pesquisa", lambda pid: estado["pesquisa"])
    monkeypatch.setattr(repo, "listar_itens", lambda pid: [item])
    monkeypatch.setattr(repo, "listar_referencias", lambda iid: [])
    monkeypatch.setattr(repo, "mover_pesquisa", lambda *a: estado["movidas"].append(a))
    monkeypatch.setattr(repo, "registrar_evento", lambda *a, **k: estado["eventos"].append((a, k)))
    monkeypatch.setattr(relatorio, "identificador_da_versao", lambda *a: "id-decisorio")
    return estado


def _banco(processo=None, dono_pesquisa=USUARIO_A, patch=None):
    b = PostgrestFalso()
    b.responder("GET", "pesquisas_preco", 200, [{"id": P, "auth_user_id": dono_pesquisa, "estado": "completed"}])
    b.responder("GET", "processos", 200, [processo or _processo()])
    if patch is not None:
        b.responder("PATCH", "processos", *patch)
    return b


def _api(emissor, banco):
    config = carregar({"APP_ENV": "test", "SUPABASE_URL": "https://exemplo-staging.supabase.co",
                       "SUPABASE_KEY": "chave-publicavel-de-teste", "PRICE_RESEARCH_ENABLED": "1"})
    rest = banco.cliente()
    return TestClient(criar_app(config, rest=rest, verificador=VerificadorSupabase(
        emissor=EMISSOR, rest=rest, chave_para=emissor.chave_para)), raise_server_exceptions=False)


def _h(emissor, **extra):
    return {"Authorization": f"Bearer {emissor.token()}", **extra}


def test_previa_mostra_antes_depois_e_documentos_que_caem(emissor, dominio):
    banco = PostgrestFalso()
    banco.responder("GET", "processos", 200, [_processo()])
    r = _api(emissor, banco).get(URL, headers=_h(emissor))
    assert r.status_code == 200, r.text
    corpo = r.json()
    assert corpo["impedimento"] == "" and corpo["versao_processo"] == VERSAO
    (m,) = corpo["mudancas"]
    assert m["unitario_atual"]["valor"] == "2.0" and m["unitario_novo"]["valor"] == "2.3450"
    assert corpo["valor_atual"]["exibicao"] == "R$ 300,00"
    assert corpo["valor_novo"]["exibicao"] == "R$ 351,75"
    assert [d["chave"] for d in corpo["documentos_a_descartar"]] == ["dfd", "etp"]
    assert not [c for c in banco.chamadas if c.method == "PATCH"], "prévia não grava"


def test_previa_de_pesquisa_nao_concluida_explica(emissor, dominio):
    dominio["pesquisa"]["estado"] = "review"
    banco = PostgrestFalso()
    banco.responder("GET", "processos", 200, [_processo()])
    r = _api(emissor, banco).get(URL, headers=_h(emissor))
    assert "Conclua a pesquisa" in r.json()["impedimento"] and r.json()["mudancas"] == []


def test_aplicar_grava_com_compare_and_set_e_marca_a_pesquisa(emissor, dominio):
    banco = _banco(patch=(200, [{"id": PROC}]))
    r = _api(emissor, banco).post(URL, headers=_h(emissor, **{"If-Match": f'"{VERSAO}"'}),
                                  json={"confirmo_descarte": True})
    assert r.status_code == 200, r.text
    assert r.json()["valor_global"]["exibicao"] == "R$ 351,75"
    assert r.json()["pesquisa_marcada"] is True
    (patch,) = [c for c in banco.chamadas if c.method == "PATCH"]
    assert patch.url.params["atualizado_em"] == f"eq.{VERSAO}"
    corpo = banco.corpo(patch)
    assert corpo["documentos"] == {} and corpo["aprovados"] == []
    assert corpo["dados"]["itens"][0]["valor_unitario"] == 2.345
    assert dominio["movidas"] and dominio["eventos"][0][0][1] == "pesquisa_aplicada"


def test_sem_confirmar_o_descarte_e_422_e_nada_grava(emissor, dominio):
    banco = _banco()
    r = _api(emissor, banco).post(URL, headers=_h(emissor, **{"If-Match": f'"{VERSAO}"'}), json={})
    assert r.status_code == 422 and r.json()["code"] == "CONFIRMAR_DESCARTE"
    assert not [c for c in banco.chamadas if c.method == "PATCH"]


def test_processo_que_mudou_e_409(emissor, dominio):
    banco = _banco()
    r = _api(emissor, banco).post(URL, headers=_h(emissor, **{"If-Match": '"versao-velha"'}),
                                  json={"confirmo_descarte": True})
    assert r.status_code == 409 and r.json()["code"] == "VERSION_CONFLICT"
    assert not [c for c in banco.chamadas if c.method == "PATCH"]


def test_corrida_no_banco_tambem_e_409(emissor, dominio):
    banco = _banco(patch=(200, []))          # o compare-and-set não casou
    r = _api(emissor, banco).post(URL, headers=_h(emissor, **{"If-Match": f'"{VERSAO}"'}),
                                  json={"confirmo_descarte": True})
    assert r.status_code == 409 and dominio["movidas"] == []


def test_sem_if_match_e_428(emissor, dominio):
    r = _api(emissor, _banco()).post(URL, headers=_h(emissor), json={"confirmo_descarte": True})
    assert r.status_code == 428


def test_dono_da_pesquisa_que_nao_e_dono_do_processo_e_403(emissor, dominio):
    banco = _banco(processo=_processo(dono=OUTRO))
    r = _api(emissor, banco).post(URL, headers=_h(emissor, **{"If-Match": f'"{VERSAO}"'}),
                                  json={"confirmo_descarte": True})
    assert r.status_code == 403 and not [c for c in banco.chamadas if c.method == "PATCH"]


def test_colega_nao_aplica_a_pesquisa_alheia(emissor, dominio):
    r = _api(emissor, _banco(dono_pesquisa=OUTRO)).post(
        URL, headers=_h(emissor, **{"If-Match": f'"{VERSAO}"'}), json={"confirmo_descarte": True})
    assert r.status_code == 403


def test_pesquisa_ja_aplicada_e_409_com_o_motivo(emissor, dominio):
    dominio["pesquisa"]["estado"] = "applied"
    r = _api(emissor, _banco()).post(URL, headers=_h(emissor, **{"If-Match": f'"{VERSAO}"'}),
                                     json={"confirmo_descarte": True})
    assert r.status_code == 409 and "já foi aplicada" in r.json()["message"]


def test_sem_documentos_nao_pede_confirmacao(emissor, dominio):
    banco = _banco(processo=_processo(documentos={}, aprovados=[]), patch=(200, [{"id": PROC}]))
    r = _api(emissor, banco).post(URL, headers=_h(emissor, **{"If-Match": f'"{VERSAO}"'}), json={})
    assert r.status_code == 200 and r.json()["documentos_descartados"] == []
