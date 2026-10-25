"""
Base de Conhecimento (M6): o que a API exige e devolve. A indexação e a
busca do domínio (`rag.*`) são substituídas; o que o banco FAZ (RLS da
0020 + 0034) é prova de `tests/test_migracao_0034.py` e da pilha real.
"""

import base64

import pytest
from fastapi.testclient import TestClient

from govconect_api.config import carregar
from govconect_api.main import criar_app
from govconect_api.verificador import VerificadorSupabase
from src import rag

from apoio_jwt import EMISSOR, TENANT_A, Emissor, PostgrestFalso

REF = "abababab-0000-4000-8000-000000000001"
TXT = base64.b64encode("Art. 1º Esta Lei estabelece normas gerais de licitação.".encode()).decode()


@pytest.fixture
def emissor():
    return Emissor()


@pytest.fixture
def falso():
    return PostgrestFalso()


@pytest.fixture
def dominio(monkeypatch):
    chamadas = {"indexar": [], "buscar": []}

    def indexar(nome, titulo, categoria, dados):
        from src import db

        chamadas["indexar"].append((nome, titulo, categoria, dados, db.tenant_atual()))
        if b"vazio" in dados:
            raise rag.ErroRAG(f"'{nome}' não gerou trechos indexáveis.")
        return rag.Indexada(documento_id=REF, trechos=3, pendente_de_vetor=b"sem-vetor" in dados)

    def buscar(consulta, *a, **k):
        chamadas["buscar"].append(consulta)
        return [{"titulo": "Lei 14.133", "categoria": "lei", "similaridade": 0.82, "conteudo": "x" * 900}]

    monkeypatch.setattr(rag, "indexar", indexar)
    monkeypatch.setattr(rag, "buscar_referencias", buscar)
    return chamadas


@pytest.fixture
def api(emissor, falso, dominio):
    config = carregar({"APP_ENV": "test", "SUPABASE_URL": "https://exemplo-staging.supabase.co",
                       "SUPABASE_KEY": "chave-publicavel-de-teste"})
    rest = falso.cliente()
    verificador = VerificadorSupabase(emissor=EMISSOR, rest=rest, chave_para=emissor.chave_para)
    return TestClient(criar_app(config, verificador=verificador, rest=rest), raise_server_exceptions=False)


def _admin(emissor):
    return {"Authorization": f"Bearer {emissor.token(papel='admin')}"}


def _pedido(**extra):
    return {"nome_arquivo": "lei.txt", "titulo": "  Lei 14.133 ", "categoria": "lei", "conteudo": TXT, **extra}


@pytest.mark.parametrize("metodo,caminho,corpo", [
    ("GET", "", None), ("POST", "", _pedido()), ("DELETE", f"/{REF}", None),
    ("POST", "/busca", {"consulta": "registro de preços"}),
])
def test_usuario_comum_nao_entra(api, emissor, dominio, metodo, caminho, corpo):
    r = api.request(metodo, f"/api/v1/admin/base-conhecimento{caminho}", json=corpo,
                    headers={"Authorization": f"Bearer {emissor.token()}"})
    assert r.status_code == 403
    assert not dominio["indexar"] and not dominio["buscar"]


def test_lista_do_tenant_com_rotulo_da_categoria(api, emissor, falso):
    falso.responder("GET", "documentos_referencia", 200, [
        {"id": REF, "titulo": "Lei 14.133", "categoria": "lei", "nome_arquivo": "lei.pdf",
         "total_chunks": 40, "criado_em": "2026-10-24T10:00:00+00:00"}])
    corpo = api.get("/api/v1/admin/base-conhecimento", headers=_admin(emissor)).json()
    assert corpo["referencias"][0]["categoria_rotulo"] == rag.CATEGORIAS["lei"]
    assert {c["codigo"] for c in corpo["categorias"]} == set(rag.CATEGORIAS)
    pedido = [c for c in falso.chamadas if c.url.path.endswith("/documentos_referencia")][-1]
    assert pedido.url.params["tenant_id"] == f"eq.{TENANT_A}"


def test_indexa_no_tenant_da_sessao_e_diz_se_ficou_pendente(api, emissor, dominio):
    r = api.post("/api/v1/admin/base-conhecimento", headers=_admin(emissor), json=_pedido())
    assert r.status_code == 201, r.text
    assert r.json() == {"id": REF, "nome_arquivo": "lei.txt", "trechos": 3, "pendente_de_vetor": False}
    nome, titulo, categoria, dados, tenant = dominio["indexar"][0]
    assert (nome, titulo, categoria, tenant) == ("lei.txt", "Lei 14.133", "lei", TENANT_A)
    assert dados.startswith("Art. 1º".encode())

    sem_vetor = base64.b64encode(b"texto sem-vetor").decode()
    r = api.post("/api/v1/admin/base-conhecimento", headers=_admin(emissor), json=_pedido(conteudo=sem_vetor))
    assert r.json()["pendente_de_vetor"] is True


@pytest.mark.parametrize("extra", [
    {"nome_arquivo": "planilha.xlsx"}, {"nome_arquivo": "sem-extensao"}, {"categoria": "inexistente"},
    {"conteudo": "não é base64!"}, {"tenant_id": "outro"},
])
def test_pedido_invalido_e_422_sem_tocar_o_dominio(api, emissor, dominio, extra):
    r = api.post("/api/v1/admin/base-conhecimento", headers=_admin(emissor), json=_pedido(**extra))
    assert r.status_code == 422
    assert not dominio["indexar"]


def test_arquivo_acima_de_10_mb_e_413(api, emissor, dominio):
    grande = base64.b64encode(b"a" * (10 * 1024 * 1024 + 1)).decode()
    r = api.post("/api/v1/admin/base-conhecimento", headers=_admin(emissor), json=_pedido(conteudo=grande))
    assert r.status_code == 413
    assert not dominio["indexar"]


def test_recusa_do_dominio_vira_422_com_a_mensagem(api, emissor):
    vazio = base64.b64encode(b"vazio").decode()
    r = api.post("/api/v1/admin/base-conhecimento", headers=_admin(emissor), json=_pedido(conteudo=vazio))
    assert r.status_code == 422
    assert "não gerou trechos indexáveis" in r.json()["message"]


def test_excluir_sem_linha_alcancada_e_404(api, emissor, falso):
    falso.responder("DELETE", "documentos_referencia", 200, [])
    assert api.delete(f"/api/v1/admin/base-conhecimento/{REF}", headers=_admin(emissor)).status_code == 404


def test_excluir_filtra_o_tenant_e_pede_a_linha_de_volta(api, emissor, falso):
    falso.responder("DELETE", "documentos_referencia", 200, [{"id": REF}])
    r = api.delete(f"/api/v1/admin/base-conhecimento/{REF}", headers=_admin(emissor))
    assert r.status_code == 200 and r.json() == {"id": REF}
    pedido = [c for c in falso.chamadas if c.method == "DELETE"][-1]
    assert pedido.url.params["id"] == f"eq.{REF}"
    assert pedido.url.params["tenant_id"] == f"eq.{TENANT_A}"
    assert "return=representation" in pedido.headers["Prefer"]


def test_busca_devolve_o_trecho_cortado(api, emissor, dominio):
    r = api.post("/api/v1/admin/base-conhecimento/busca", headers=_admin(emissor),
                 json={"consulta": "  registro de preços  "})
    assert r.status_code == 200
    assert dominio["buscar"] == ["registro de preços"]
    trecho = r.json()[0]
    assert trecho["categoria_rotulo"] == rag.CATEGORIAS["lei"] and len(trecho["conteudo"]) == 400
