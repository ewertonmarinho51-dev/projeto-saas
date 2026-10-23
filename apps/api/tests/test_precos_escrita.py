"""
Pesquisa de preços pela API, escrita (P04e): criar, importar planilha,
concluir e reabrir item.

PostgREST simulado; o domínio de importação é o VERDADEIRO (diagnóstico e
plano sobre um XLSX real), só o repositório é substituído. O que se prova:
o plano é conferido pelo servidor (hash), nada é gravado antes da
confirmação nem com planilha com erro, dono/admin para escrever,
idempotência da criação e o If-Match do item.
"""

import io
import uuid
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient

from govconect_api.config import carregar
from govconect_api.main import criar_app
from govconect_api.verificador import VerificadorSupabase
from src.precos import cotacoes
from src.precos import repositorio as repo

from apoio_jwt import EMISSOR, TENANT_A, USUARIO_A, Emissor, PostgrestFalso

P = "eeeeeeee-0000-4000-8000-000000000001"
I = "eeeeeeee-0000-4000-8000-0000000000a1"
OUTRO = "99999999-0000-4000-8000-000000000009"
XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


def _planilha(linhas):
    from openpyxl import Workbook

    wb = Workbook()
    ws = wb.active
    ws.append(["Código", "Descrição", "Unidade", "Quantidade"])
    for linha in linhas:
        ws.append(linha)
    saida = io.BytesIO()
    wb.save(saida)
    return saida.getvalue()


BOA = _planilha([["451234", "Caneta esferográfica azul", "UN", 150],
                 ["", "Papel A4 75 g/m²", "RESMA", "12,5"]])
RUIM = _planilha([["", "Caneta", "UNIDADE-QUE-NAO-EXISTE", 10]])


@pytest.fixture
def emissor():
    return Emissor()


def _banco(dono=USUARIO_A):
    b = PostgrestFalso()
    b.responder("GET", "pesquisas_preco", 200, [{"id": P, "auth_user_id": dono, "estado": "draft"}])
    return b


def _api(emissor, banco):
    config = carregar({"APP_ENV": "test", "SUPABASE_URL": "https://exemplo-staging.supabase.co",
                       "SUPABASE_KEY": "chave-publicavel-de-teste", "PRICE_RESEARCH_ENABLED": "1"})
    rest = banco.cliente()
    return TestClient(criar_app(config, rest=rest, verificador=VerificadorSupabase(
        emissor=EMISSOR, rest=rest, chave_para=emissor.chave_para)), raise_server_exceptions=False)


def _h(emissor, **extra):
    return {"Authorization": f"Bearer {emissor.token()}", **extra}


@pytest.fixture
def dominio(monkeypatch):
    estado = {"itens": [], "gravados": [], "eventos": [], "criadas": [], "por_chave": None}
    monkeypatch.setattr(repo, "obter_pesquisa", lambda pid: {"id": pid, "estado": "draft"})
    monkeypatch.setattr(repo, "listar_itens", lambda pid: list(estado["itens"]))
    monkeypatch.setattr(repo, "salvar_itens", lambda pid, itens: estado["gravados"].extend(itens) or itens)
    monkeypatch.setattr(repo, "registrar_evento", lambda *a, **k: estado["eventos"].append((a, k)))
    monkeypatch.setattr(cotacoes, "sincronizar_estado", lambda pid: "draft")
    monkeypatch.setattr(repo, "obter_por_chave", lambda chave: estado["por_chave"])

    def criar(ctx, dados, *, idempotency_key=""):
        estado["criadas"].append((ctx, dados, idempotency_key))
        return {"id": P, "nome": dados["nome"], "estado": "draft"}

    monkeypatch.setattr(cotacoes, "criar_cotacao", criar)
    return estado


# ---------------------------------------------------------------------------
# Criar
# ---------------------------------------------------------------------------
URL = "/api/v1/precos/pesquisas"


def test_cria_pesquisa_com_chave_do_usuario(emissor, dominio):
    r = _api(emissor, PostgrestFalso()).post(URL, headers=_h(emissor, **{"Idempotency-Key": "nova-0001"}),
                                             json={"nome": "Material de expediente"})
    assert r.status_code == 201, r.text
    assert r.headers["Location"].endswith(P)
    (ctx, dados, chave), = dominio["criadas"]
    assert ctx.auth_user_id == USUARIO_A and dados["nome"] == "Material de expediente"
    assert chave == f"api:{USUARIO_A}:nova-0001"


def test_mesma_chave_devolve_a_mesma_pesquisa(emissor, dominio):
    dominio["por_chave"] = {"id": P, "nome": "Já existe", "estado": "draft"}
    r = _api(emissor, PostgrestFalso()).post(URL, headers=_h(emissor, **{"Idempotency-Key": "nova-0002"}),
                                             json={"nome": "Outra coisa"})
    assert r.status_code == 200 and r.headers["Idempotent-Replayed"] == "true"
    assert dominio["criadas"] == []


def test_processo_fora_do_acesso_e_404(emissor, dominio):
    banco = PostgrestFalso()
    banco.responder("GET", "processos", 200, [])
    r = _api(emissor, banco).post(URL, headers=_h(emissor, **{"Idempotency-Key": "nova-0003"}),
                                  json={"nome": "X", "processo_id": str(uuid.uuid4())})
    assert r.status_code == 404 and dominio["criadas"] == []


@pytest.mark.parametrize("corpo", [{"nome": ""}, {"nome": "X", "perfil_normativo": "inventado"},
                                   {"nome": "X", "tenant_id": TENANT_A}])
def test_pedido_invalido(emissor, dominio, corpo):
    r = _api(emissor, PostgrestFalso()).post(URL, headers=_h(emissor, **{"Idempotency-Key": "nova-0004"}),
                                             json=corpo)
    assert r.status_code == 422 and dominio["criadas"] == []


# ---------------------------------------------------------------------------
# Importar
# ---------------------------------------------------------------------------
URL_IMP = f"/api/v1/precos/pesquisas/{P}/importacao"


def _importar(emissor, banco, corpo=BOA, confirmar=False, plano=None, tipo=XLSX):
    cab = _h(emissor, **{"Content-Type": tipo})
    if plano:
        cab["If-Match"] = f'"{plano}"'
    return _api(emissor, banco).post(URL_IMP + ("?confirmar=true" if confirmar else ""),
                                     headers=cab, content=corpo)


def test_conferir_nao_grava_e_devolve_o_plano(emissor, dominio):
    r = _importar(emissor, _banco())
    assert r.status_code == 200, r.text
    corpo = r.json()
    assert corpo["pode_importar"] and corpo["gravado"] is False
    assert corpo["resumo"]["novo"] == 2
    assert [a["quantidade"] for a in corpo["acoes"]] == ["150", "12.5"]
    assert dominio["gravados"] == []


def test_confirmar_com_o_plano_conferido_grava(emissor, dominio):
    plano = _importar(emissor, _banco()).json()["plano"]
    r = _importar(emissor, _banco(), confirmar=True, plano=plano)
    assert r.status_code == 200 and r.json()["gravado"] is True
    assert [i["descricao"] for i in dominio["gravados"]] == ["Caneta esferográfica azul", "Papel A4 75 g/m²"]
    assert dominio["gravados"][1]["quantidade"] == Decimal("12.5")


def test_cotacao_que_mudou_desde_a_conferencia_e_409(emissor, dominio):
    plano = _importar(emissor, _banco()).json()["plano"]
    dominio["itens"] = [{"id": "x", "numero": 1, "descricao": "Outro item", "unidade": "UN",
                         "quantidade": 1, "estado": "pending"}]
    r = _importar(emissor, _banco(), confirmar=True, plano=plano)
    assert r.status_code == 409 and r.json()["code"] == "PLANO_DESATUALIZADO"
    assert dominio["gravados"] == []


def test_confirmar_sem_if_match_e_428(emissor, dominio):
    assert _importar(emissor, _banco(), confirmar=True).status_code == 428


def test_planilha_com_erro_nao_grava(emissor, dominio):
    conferido = _importar(emissor, _banco(), corpo=RUIM).json()
    assert conferido["pode_importar"] is False and conferido["erros"]
    r = _importar(emissor, _banco(), corpo=RUIM, confirmar=True, plano=conferido["plano"])
    assert r.status_code == 422 and dominio["gravados"] == []


@pytest.mark.parametrize("tipo,corpo", [("text/csv", b"a,b"), (XLSX, b"isto nao e xlsx")])
def test_arquivo_que_nao_e_xlsx(emissor, dominio, tipo, corpo):
    assert _importar(emissor, _banco(), corpo=corpo, tipo=tipo).status_code == 415


def test_colega_nao_importa(emissor, dominio):
    assert _importar(emissor, _banco(dono=OUTRO)).status_code == 403


# ---------------------------------------------------------------------------
# Concluir e reabrir
# ---------------------------------------------------------------------------
def _banco_com_item():
    b = _banco()
    b.responder("GET", "pesquisa_preco_itens", 200, [{"id": I}])
    return b


def test_concluir_exige_if_match(emissor, dominio):
    r = _api(emissor, _banco_com_item()).post(f"{URL}/{P}/itens/{I}/conclusao",
                                              headers=_h(emissor), json={})
    assert r.status_code == 428


def test_concluir_passa_justificativa_e_revisao(emissor, dominio, monkeypatch):
    chamadas = []
    monkeypatch.setattr(cotacoes, "concluir_item",
                        lambda ctx, p, i, **k: chamadas.append((ctx.auth_user_id, p, i, k)))
    monkeypatch.setattr(repo, "obter_item", lambda i: {"id": i, "estado": "complete", "revisao": 4})
    r = _api(emissor, _banco_com_item()).post(f"{URL}/{P}/itens/{I}/conclusao",
                                              headers=_h(emissor, **{"If-Match": '"3"'}),
                                              json={"justificativa": "conferido na fonte"})
    assert r.status_code == 200 and r.json() == {"id": I, "estado": "complete", "revisao": 4}
    assert chamadas == [(USUARIO_A, P, I, {"justificativa": "conferido na fonte", "revisao_esperada": 3})]


def test_regra_do_dominio_volta_como_422_com_a_mensagem(emissor, dominio, monkeypatch):
    def recusa(*a, **k):
        raise cotacoes.ErroCotacao("Este item tem pendência de análise crítica.")

    monkeypatch.setattr(cotacoes, "concluir_item", recusa)
    r = _api(emissor, _banco_com_item()).post(f"{URL}/{P}/itens/{I}/conclusao",
                                              headers=_h(emissor, **{"If-Match": '"3"'}), json={})
    assert r.status_code == 422 and "pendência" in r.json()["message"]


def test_conflito_de_versao_e_409(emissor, dominio, monkeypatch):
    def conflito(*a, **k):
        raise repo.ConflitoDeVersao("mudou")

    monkeypatch.setattr(cotacoes, "concluir_item", conflito)
    r = _api(emissor, _banco_com_item()).post(f"{URL}/{P}/itens/{I}/conclusao",
                                              headers=_h(emissor, **{"If-Match": '"3"'}), json={})
    assert r.status_code == 409 and r.json()["code"] == "VERSION_CONFLICT"


def test_reabrir_com_motivo(emissor, dominio, monkeypatch):
    chamadas = []
    monkeypatch.setattr(cotacoes, "reabrir_item", lambda ctx, p, i, motivo: chamadas.append(motivo))
    monkeypatch.setattr(repo, "obter_item", lambda i: {"id": i, "estado": "review", "revisao": 5})
    r = _api(emissor, _banco_com_item()).post(f"{URL}/{P}/itens/{I}/reabertura",
                                              headers=_h(emissor), json={"motivo": "faltou um preço"})
    assert r.status_code == 200 and chamadas == ["faltou um preço"]


def test_colega_nao_conclui(emissor, dominio, monkeypatch):
    monkeypatch.setattr(cotacoes, "concluir_item", lambda *a, **k: pytest.fail("não podia"))
    r = _api(emissor, _banco(dono=OUTRO)).post(f"{URL}/{P}/itens/{I}/conclusao",
                                               headers=_h(emissor, **{"If-Match": '"3"'}), json={})
    assert r.status_code == 403
