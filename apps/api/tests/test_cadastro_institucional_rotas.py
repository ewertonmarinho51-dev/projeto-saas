"""
Prefeitura, Secretarias e Identidade visual (M7b): o que a API exige e
devolve. O domínio (`db.*`) é substituído por um cadastro em memória; a
captura do timbrado (`branding`) roda de verdade sobre um PDF gerado aqui.
O que o banco FAZ (RLS da 0035) é prova de `tests/test_migracao_0035.py`.
"""

import base64
import io

import pytest
from fastapi.testclient import TestClient
from PIL import Image

from govconect_api.config import carregar
from govconect_api.main import criar_app
from govconect_api.verificador import VerificadorSupabase
from src import db

from apoio_jwt import EMISSOR, TENANT_A, Emissor, PostgrestFalso

SEC = "dddddddd-0000-4000-8000-000000000001"
SEC2 = "dddddddd-0000-4000-8000-000000000002"
ORG = "cccccccc-0000-4000-8000-000000000001"
PNG = base64.b64encode(b"\x89PNG\r\n\x1a\nconteudo").decode()
BASE = "/api/v1/admin/instituicao"


def _pdf() -> str:
    pagina = Image.new("RGB", (595, 842), "white")
    saida = io.BytesIO()
    pagina.save(saida, format="PDF")
    return base64.b64encode(saida.getvalue()).decode()


@pytest.fixture
def cadastro(monkeypatch):
    estado = {
        "flags": {"multi_prefeituras": True},
        "config": {},
        "tenant": {"id": TENANT_A, "nome": "Prefeitura A", "cnpj": "00.000.000/0001-00"},
        "secretarias": [
            {"id": SEC, "nome": "Administração", "sigla": "SEMAD", "ativo": True, "padrao": True,
             "cabecalho_img": PNG},
            {"id": SEC2, "nome": "Educação", "sigla": "", "ativo": True, "padrao": False},
        ],
        "orgaos": [{"id": ORG, "orgao": "Prefeitura A", "padrao": True, "cabecalho_img": PNG,
                    "rodape_img": PNG, "cabecalho": "", "rodape": "", "marca_dagua": ""}],
        "gravacoes": [],
    }
    monkeypatch.setattr(db, "flag_ativa", lambda nome: estado["flags"].get(nome, False))
    monkeypatch.setattr(db, "obter_config", lambda chave: estado["config"].get(chave, ""))
    monkeypatch.setattr(db, "tenant_atual_registro", lambda: estado["tenant"])

    def salvar_dados(registro):
        estado["gravacoes"].append(("tenant", db.tenant_atual(), registro))
        estado["tenant"].update(registro)
    monkeypatch.setattr(db, "salvar_dados_do_tenant", salvar_dados)
    monkeypatch.setattr(db, "listar_secretarias", lambda incluir_inativas=False: estado["secretarias"])

    def salvar_secretaria(registro, secretaria_id=None):
        estado["gravacoes"].append(("secretaria", secretaria_id, registro))
        if secretaria_id is None:
            estado["secretarias"].append({"id": "dddddddd-0000-4000-8000-0000000000ff", "ativo": True,
                                          "padrao": False, **registro})
    monkeypatch.setattr(db, "salvar_secretaria", salvar_secretaria)
    monkeypatch.setattr(db, "listar_orgaos", lambda: estado["orgaos"])

    def salvar_orgao(registro, orgao_id=None):
        estado["gravacoes"].append(("orgao", orgao_id, registro))
    monkeypatch.setattr(db, "salvar_orgao", salvar_orgao)
    return estado


@pytest.fixture
def emissor():
    return Emissor()


@pytest.fixture
def falso():
    return PostgrestFalso()


@pytest.fixture
def api(emissor, falso, cadastro):
    config = carregar({"APP_ENV": "test", "SUPABASE_URL": "https://exemplo-staging.supabase.co",
                       "SUPABASE_KEY": "chave-publicavel-de-teste"})
    rest = falso.cliente()
    verificador = VerificadorSupabase(emissor=EMISSOR, rest=rest, chave_para=emissor.chave_para)
    return TestClient(criar_app(config, verificador=verificador, rest=rest), raise_server_exceptions=False)


def _admin(emissor):
    return {"Authorization": f"Bearer {emissor.token(papel='admin')}"}


@pytest.mark.parametrize("metodo,caminho,corpo", [
    ("GET", "/prefeitura", None), ("PUT", "/prefeitura", {"cidade": "x"}),
    ("GET", "/secretarias", None), ("POST", "/secretarias", {"nome": "x"}),
    ("PATCH", f"/secretarias/{SEC2}", {"ativo": False}), ("GET", "/identidades", None),
    ("POST", "/identidades/texto", {"orgao": "x"}), ("PUT", f"/identidades/{ORG}/padrao", None),
    ("DELETE", f"/identidades/{ORG}", None),
])
def test_usuario_comum_nao_entra(api, emissor, cadastro, metodo, caminho, corpo):
    r = api.request(metodo, BASE + caminho, json=corpo, headers={"Authorization": f"Bearer {emissor.token()}"})
    assert r.status_code == 403
    assert not cadastro["gravacoes"]


def test_cadastro_desligado_e_404(api, emissor, cadastro):
    cadastro["flags"]["multi_prefeituras"] = False
    assert api.get(BASE + "/secretarias", headers=_admin(emissor)).status_code == 404


def test_secao_admin_desligada_some_com_prefeitura_timbrado_e_modulos(api, emissor, cadastro):
    cadastro["config"]["flag_multi_tenant_admin"] = "0"
    secoes = api.get(BASE, headers=_admin(emissor)).json()["secoes"]
    assert secoes == ["Secretarias", "Identidade visual", "Servidores", "Portarias"]
    assert api.get(BASE + "/prefeitura", headers=_admin(emissor)).status_code == 404


def test_prefeitura_le_e_grava_so_os_campos_institucionais(api, emissor, cadastro):
    corpo = api.get(BASE + "/prefeitura", headers=_admin(emissor)).json()
    assert [c["chave"] for c in corpo["campos"]] == [
        "nome_oficial", "cnpj", "sigla", "cidade", "endereco", "telefone", "email", "site"]
    assert next(c for c in corpo["campos"] if c["chave"] == "cnpj")["valor"] == "00.000.000/0001-00"
    r = api.put(BASE + "/prefeitura", headers=_admin(emissor), json={"cidade": "  Paragominas ", "cnpj": ""})
    assert r.status_code == 200, r.text
    _, tenant, registro = cadastro["gravacoes"][-1]
    assert tenant == TENANT_A
    assert registro["cidade"] == "Paragominas" and registro["cnpj"] is None and registro["site"] is None


@pytest.mark.parametrize("corpo", [{"slug": "outra"}, {"nome": "Outra"}, {"tenant_id": "x"}, {"cidade": "x" * 121}])
def test_prefeitura_recusa_o_que_nao_e_cadastro(api, emissor, cadastro, corpo):
    assert api.put(BASE + "/prefeitura", headers=_admin(emissor), json=corpo).status_code == 422
    assert not cadastro["gravacoes"]


def test_cria_secretaria_sem_tenant_no_corpo_e_recusa_nome_repetido(api, emissor, cadastro):
    r = api.post(BASE + "/secretarias", headers=_admin(emissor), json={"nome": " Saúde ", "sigla": "SESAU"})
    assert r.status_code == 201 and any(s["nome"] == "Saúde" for s in r.json())
    assert cadastro["gravacoes"][-1] == ("secretaria", None, {"nome": "Saúde", "sigla": "SESAU"})
    assert api.post(BASE + "/secretarias", headers=_admin(emissor), json={"nome": "educação"}).status_code == 409
    assert api.post(BASE + "/secretarias", headers=_admin(emissor),
                    json={"nome": "x", "tenant_id": "outro"}).status_code == 422


def test_desativa_e_so_quem_tem_timbrado_vira_padrao(api, emissor, cadastro):
    r = api.patch(f"{BASE}/secretarias/{SEC2}", headers=_admin(emissor), json={"ativo": False})
    assert r.status_code == 200 and cadastro["gravacoes"][-1] == ("secretaria", SEC2, {"ativo": False})
    r = api.patch(f"{BASE}/secretarias/{SEC2}", headers=_admin(emissor), json={"padrao": True})
    assert r.status_code == 422 and "identidade visual própria" in r.json()["message"]
    secretarias = api.get(BASE + "/secretarias", headers=_admin(emissor)).json()
    assert next(s for s in secretarias if s["id"] == SEC)["identidade_propria"] is True


def test_secretaria_de_fora_e_404(api, emissor):
    r = api.patch(f"{BASE}/secretarias/dddddddd-0000-4000-8000-0000000000aa", headers=_admin(emissor),
                  json={"ativo": False})
    assert r.status_code == 404


def test_previa_recorta_o_pdf_e_recusa_docx(api, emissor, cadastro):
    pedido = {"nome_arquivo": "modelo.pdf", "conteudo": _pdf(), "cabecalho_pct": 14, "rodape_pct": 10,
              "marca": True}
    r = api.post(BASE + "/identidades/previa", headers=_admin(emissor), json=pedido)
    assert r.status_code == 200, r.text
    corpo = r.json()
    assert all(corpo[k].startswith("data:image/png;base64,") for k in ("pagina", "cabecalho", "rodape", "marca"))
    docx = {**pedido, "nome_arquivo": "modelo.docx"}
    assert api.post(BASE + "/identidades/previa", headers=_admin(emissor), json=docx).status_code == 422
    falso_pdf = {**pedido, "conteudo": base64.b64encode(b"nao sou pdf").decode()}
    assert api.post(BASE + "/identidades/previa", headers=_admin(emissor), json=falso_pdf).status_code == 422
    assert not cadastro["gravacoes"]


def test_salva_identidade_por_imagem_com_os_recortes(api, emissor, cadastro):
    r = api.post(BASE + "/identidades/imagem", headers=_admin(emissor), json={
        "nome_arquivo": "modelo.pdf", "conteudo": _pdf(), "cabecalho_pct": 20, "rodape_pct": 8,
        "orgao": "Prefeitura A", "padrao": True})
    assert r.status_code == 201, r.text
    _, orgao_id, registro = cadastro["gravacoes"][-1]
    assert orgao_id is None and registro["padrao"] is True and registro["marca_img"] == ""
    assert registro["cabecalho_pct"] == 20.0 and registro["cabecalho_img"] and registro["rodape_img"]


def test_salva_identidade_por_texto_e_torna_padrao(api, emissor, cadastro):
    r = api.post(BASE + "/identidades/texto", headers=_admin(emissor),
                 json={"orgao": "SEMED", "cabecalho": "PREFEITURA · SEMED", "padrao": False})
    assert r.status_code == 201
    assert cadastro["gravacoes"][-1][2]["cabecalho"] == "PREFEITURA · SEMED"
    assert api.put(f"{BASE}/identidades/{ORG}/padrao", headers=_admin(emissor)).status_code == 200
    assert cadastro["gravacoes"][-1] == ("orgao", ORG, {"padrao": True})
    fora = api.put(f"{BASE}/identidades/cccccccc-0000-4000-8000-0000000000aa/padrao", headers=_admin(emissor))
    assert fora.status_code == 404


def test_excluir_identidade_filtra_o_tenant_e_zero_linhas_e_404(api, emissor, falso):
    falso.responder("DELETE", "config_orgaos", 200, [])
    assert api.delete(f"{BASE}/identidades/{ORG}", headers=_admin(emissor)).status_code == 404
    falso.responder("DELETE", "config_orgaos", 200, [{"id": ORG}])
    r = api.delete(f"{BASE}/identidades/{ORG}", headers=_admin(emissor))
    assert r.status_code == 200 and r.json() == {"id": ORG}
    pedido = [c for c in falso.chamadas if c.method == "DELETE"][-1]
    assert pedido.url.params["tenant_id"] == f"eq.{TENANT_A}"
    assert "return=representation" in pedido.headers["Prefer"]
