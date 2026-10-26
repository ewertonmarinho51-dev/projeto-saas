"""
Gestão da cotação e dos itens pela API (M10a): duplicar, arquivar,
incluir/editar/retirar item, desfazer retirada e manter preço.

PostgREST simulado; o domínio (`cotacoes.*`) é substituído e REGISTRA o
que recebeu — as regras dele têm prova própria em `tests/`. O que se
prova aqui: a guarda (404 fora do acesso, 403 sem ser dono, 409 item
concluído), o If-Match, a tradução dos erros do domínio e que o corpo
chega ao domínio sem conversão para float.
"""

from decimal import Decimal
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from govconect_api.config import carregar
from govconect_api.main import criar_app
from govconect_api.verificador import VerificadorSupabase
from src.precos import cotacoes
from src.precos import repositorio as repo

from apoio_jwt import EMISSOR, USUARIO_A, Emissor, PostgrestFalso

P = "eeeeeeee-0000-4000-8000-000000000001"
I = "eeeeeeee-0000-4000-8000-0000000000a1"
R = "eeeeeeee-0000-4000-8000-0000000000f1"
OUTRO = "99999999-0000-4000-8000-000000000009"
BASE = f"/api/v1/precos/pesquisas/{P}"


@pytest.fixture
def emissor():
    return Emissor()


def _banco(dono=USUARIO_A, estado="draft", item_estado="in_review", item=True):
    b = PostgrestFalso()
    for _ in range(3):
        b.responder("GET", "pesquisas_preco", 200, [{"id": P, "nome": "Canetas", "auth_user_id": dono, "estado": estado}])
        b.responder("GET", "pesquisa_preco_itens", 200, [{"id": I, "estado": item_estado}] if item else [])
    return b


def _api(emissor, banco):
    config = carregar({"APP_ENV": "test", "SUPABASE_URL": "https://exemplo-staging.supabase.co",
                       "SUPABASE_KEY": "chave-publicavel-de-teste", "PRICE_RESEARCH_ENABLED": "1"})
    rest = banco.cliente()
    return TestClient(criar_app(config, rest=rest, verificador=VerificadorSupabase(
        emissor=EMISSOR, rest=rest, chave_para=emissor.chave_para)), raise_server_exceptions=False)


def _h(emissor, papel="usuario", **extra):
    return {"Authorization": f"Bearer {emissor.token(papel=papel)}", **extra}


@pytest.fixture
def dominio(monkeypatch):
    chamadas: list = []
    estimativa = SimpleNamespace(valor_unitario=Decimal("1.50"), metodo="media", status="CONCLUIDO",
                                 pendencias=[])

    def registra(nome, devolve=None, erro=None):
        def f(*a, **k):
            chamadas.append((nome, a, k))
            if erro:
                raise erro
            return devolve
        return f

    monkeypatch.setattr(repo, "obter_item", lambda iid: {"id": iid, "estado": "in_review", "revisao": 8})
    monkeypatch.setattr(cotacoes, "duplicar", registra("duplicar", {"id": OUTRO, "nome": "Canetas (cópia)",
                                                                    "estado": "draft"}))
    monkeypatch.setattr(cotacoes, "arquivar", registra("arquivar", {"id": P, "nome": "Canetas", "estado": "archived"}))
    monkeypatch.setattr(cotacoes, "salvar_item", registra("salvar_item", {"id": I}))
    monkeypatch.setattr(cotacoes, "remover_item", registra("remover_item", {"id": I}))
    monkeypatch.setattr(cotacoes, "desfazer_retirada", registra("desfazer", estimativa))
    monkeypatch.setattr(cotacoes, "manter_referencia", registra("manter", estimativa))
    return {"chamadas": chamadas, "registra": registra, "monkeypatch": monkeypatch}


def test_duplicar_basta_ler_e_a_copia_e_de_quem_duplica(emissor, dominio):
    api = _api(emissor, _banco(dono="outra-pessoa"))
    r = api.post(f"{BASE}/duplicacao", headers=_h(emissor))
    assert r.status_code == 201, r.text
    assert r.json() == {"id": OUTRO, "nome": "Canetas (cópia)", "estado": "draft"}
    nome, args, _ = dominio["chamadas"][-1]
    assert nome == "duplicar" and args[0].auth_user_id == USUARIO_A and args[1] == P


def test_fora_do_acesso_e_404_sem_tocar_o_dominio(emissor, dominio):
    banco = PostgrestFalso()
    banco.responder("GET", "pesquisas_preco", 200, [])
    api = _api(emissor, banco)
    assert api.post(f"{BASE}/duplicacao", headers=_h(emissor)).status_code == 404
    assert not dominio["chamadas"]


@pytest.mark.parametrize("metodo,caminho,corpo,cabecalho", [
    ("POST", "/arquivamento", None, {}),
    ("POST", "/itens", {"descricao": "Caneta azul", "unidade": "UN", "quantidade": "10"}, {}),
    ("PUT", f"/itens/{I}", {"descricao": "Caneta azul", "unidade": "UN", "quantidade": "10"}, {"If-Match": '"8"'}),
    ("POST", f"/itens/{I}/retirada", {}, {}),
    ("POST", f"/itens/{I}/referencias/{R}/manter", None, {"If-Match": '"8"'}),
])
def test_so_dono_ou_admin_escreve(emissor, dominio, metodo, caminho, corpo, cabecalho):
    api = _api(emissor, _banco(dono="outra-pessoa"))
    r = api.request(metodo, BASE + caminho, json=corpo, headers=_h(emissor, **cabecalho))
    assert r.status_code == 403
    assert not dominio["chamadas"]
    api = _api(emissor, _banco(dono="outra-pessoa"))
    r = api.request(metodo, BASE + caminho, json=corpo, headers=_h(emissor, papel="admin", **cabecalho))
    assert r.status_code in (200, 201), r.text


def test_arquivar_ja_arquivada_nao_repete_a_trilha(emissor, dominio):
    api = _api(emissor, _banco(estado="archived"))
    r = api.post(f"{BASE}/arquivamento", headers=_h(emissor))
    assert r.status_code == 200 and r.json()["estado"] == "archived"
    assert not dominio["chamadas"]


def test_incluir_item_manda_a_quantidade_em_texto(emissor, dominio):
    api = _api(emissor, _banco())
    r = api.post(f"{BASE}/itens", headers=_h(emissor),
                 json={"descricao": " Caneta esferográfica azul ", "unidade": "UN", "quantidade": "1.234,5",
                       "codigo": "451234"})
    assert r.status_code == 201, r.text
    assert r.json() == {"id": I, "estado": "in_review", "revisao": 8}
    _, args, kwargs = dominio["chamadas"][-1]
    assert args[2]["quantidade"] == "1.234,5" and args[2]["descricao"] == "Caneta esferográfica azul"
    assert "item_id" not in kwargs


@pytest.mark.parametrize("corpo", [
    {"descricao": "ab", "unidade": "UN", "quantidade": "1"},
    {"descricao": "Caneta", "unidade": "UN", "quantidade": 1.5},
    {"descricao": "Caneta", "unidade": "UN", "quantidade": "1", "tenant_id": "x"},
])
def test_item_invalido_e_422_sem_tocar_o_dominio(emissor, dominio, corpo):
    api = _api(emissor, _banco())
    assert api.post(f"{BASE}/itens", headers=_h(emissor), json=corpo).status_code == 422
    assert not dominio["chamadas"]


def test_editar_item_exige_if_match_e_passa_a_revisao(emissor, dominio):
    corpo = {"descricao": "Caneta azul", "unidade": "UN", "quantidade": "10"}
    api = _api(emissor, _banco())
    assert api.put(f"{BASE}/itens/{I}", headers=_h(emissor), json=corpo).status_code == 428
    api = _api(emissor, _banco())
    r = api.put(f"{BASE}/itens/{I}", headers=_h(emissor, **{"If-Match": '"7"'}), json=corpo)
    assert r.status_code == 200, r.text
    _, _, kwargs = dominio["chamadas"][-1]
    assert kwargs == {"item_id": I, "revisao_esperada": 7}


@pytest.mark.parametrize("erro,status", [
    (repo.ConflitoDeVersao("mudou"), 409),
    (cotacoes.CotacaoImutavel("aplicada"), 409),
    (cotacoes.ErroCotacao("unidade 'XYZ' não reconhecida"), 422),
])
def test_erros_do_dominio_viram_o_codigo_certo(emissor, dominio, erro, status):
    dominio["monkeypatch"].setattr(cotacoes, "salvar_item", dominio["registra"]("salvar_item", erro=erro))
    api = _api(emissor, _banco())
    r = api.put(f"{BASE}/itens/{I}", headers=_h(emissor, **{"If-Match": '"8"'}),
                json={"descricao": "Caneta azul", "unidade": "XYZ", "quantidade": "1"})
    assert r.status_code == status
    if status == 422:
        assert "não reconhecida" in r.json()["message"]


def test_retirar_item_com_motivo_opcional(emissor, dominio):
    api = _api(emissor, _banco())
    assert api.post(f"{BASE}/itens/{I}/retirada", headers=_h(emissor)).status_code == 200
    assert dominio["chamadas"][-1][1][3] is None
    api = _api(emissor, _banco())
    assert api.post(f"{BASE}/itens/{I}/retirada", headers=_h(emissor), json={"motivo": "duplicado"}).status_code == 200
    assert dominio["chamadas"][-1][1][3] == "duplicado"


def test_item_de_outra_pesquisa_e_404(emissor, dominio):
    api = _api(emissor, _banco(item=False))
    assert api.post(f"{BASE}/itens/{I}/retirada", headers=_h(emissor)).status_code == 404
    assert not dominio["chamadas"]


@pytest.mark.parametrize("acao,nome", [("desfazer", "desfazer"), ("manter", "manter")])
def test_cesta_exige_if_match_e_item_aberto(emissor, dominio, acao, nome):
    caminho = f"{BASE}/itens/{I}/referencias/{R}/{acao}"
    assert _api(emissor, _banco()).post(caminho, headers=_h(emissor)).status_code == 428
    concluido = _api(emissor, _banco(item_estado="complete"))
    assert concluido.post(caminho, headers=_h(emissor, **{"If-Match": '"8"'})).status_code == 409
    assert not dominio["chamadas"]
    r = _api(emissor, _banco()).post(caminho, headers=_h(emissor, **{"If-Match": '"8"'}))
    assert r.status_code == 200, r.text
    assert r.json()["revisao"] == 8 and r.json()["preco_estimado"]["valor"] == "1.50"
    nome_chamado, args, kwargs = dominio["chamadas"][-1]
    assert nome_chamado == nome and args[1:] == (P, I, R) and kwargs == {"revisao_esperada": 8}


def test_alertas_basta_ler_e_traz_a_faixa_dos_demais(emissor, dominio):
    dominio["monkeypatch"].setattr(repo, "listar_referencias", lambda iid: [])
    dominio["monkeypatch"].setattr(cotacoes, "alertas_do_item", lambda item, refs: [
        {"linha": {"id": R}, "outros": [Decimal("2.10"), Decimal("1.90")], "mantida": None},
        {"linha": {"id": I}, "outros": [], "mantida": {"registrado_por": USUARIO_A}}])
    api = _api(emissor, _banco(dono="outra-pessoa"))
    r = api.get(f"{BASE}/itens/{I}/alertas", headers=_h(emissor))
    assert r.status_code == 200, r.text
    primeiro, segundo = r.json()
    assert primeiro["referencia_id"] == R and primeiro["mantida"] is False
    assert (primeiro["faixa_min"]["valor"], primeiro["faixa_max"]["valor"]) == ("1.90", "2.10")
    assert segundo["mantida"] is True and segundo["faixa_min"] is None
