"""
Formulário Matriz (M1) contra um PostgREST SIMULADO: o que a API manda ao
banco e o que devolve. Isolamento A×B e trava otimista de verdade ficam
com `tests_rls/` (pilha real).
"""

import io

import pytest
from fastapi.testclient import TestClient
from openpyxl import Workbook

from govconect_api.config import carregar
from govconect_api.main import criar_app
from govconect_api.verificador import VerificadorSupabase

from apoio_jwt import EMISSOR, SECRETARIA_A, USUARIO_A, Emissor, PostgrestFalso

ID = "cccccccc-0000-4000-8000-000000000001"
VERSAO = "2026-10-22T14:00:00.123456+00:00"
NOVA = "2026-10-22T14:05:00.000000+00:00"
XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"

COMPLETO = {
    "orgao": "Secretaria de Saúde", "objeto": "Aquisição de luvas",
    "justificativa": "Reposição do estoque das unidades.",
    "modelo_execucao": "Entrega parcelada",
    "itens": [{"codigo": "1", "descricao": "Luva de procedimento", "unidade": "CX",
               "quantidade": "10", "valor_unitario": "25,50"}],
}


def _linha(**extra):
    base = {"id": ID, "nome": "", "orgao": "Secretaria de Saúde", "objeto": "Aquisição de luvas",
            "etapa": 0, "dados": {"orgao": "Secretaria de Saúde", "objeto": "Aquisição de luvas"},
            "documentos": {}, "aprovados": [], "criado_em": VERSAO, "atualizado_em": VERSAO,
            "secretaria_id": SECRETARIA_A, "auth_user_id": USUARIO_A, "idempotency_key": "chave-0001"}
    return {**base, **extra}


@pytest.fixture
def emissor():
    return Emissor()


@pytest.fixture
def banco():
    return PostgrestFalso()


@pytest.fixture
def api(emissor, banco):
    config = carregar({"APP_ENV": "test", "SUPABASE_URL": "https://exemplo-staging.supabase.co",
                       "SUPABASE_KEY": "chave-publicavel-de-teste"})
    rest = banco.cliente()
    verificador = VerificadorSupabase(emissor=EMISSOR, rest=rest, chave_para=emissor.chave_para)
    return TestClient(criar_app(config, verificador=verificador, rest=rest), raise_server_exceptions=False)


def _auth(emissor, **kw):
    return {"Authorization": f"Bearer {emissor.token(**kw)}"}


def _put(api, emissor, corpo, versao=VERSAO, **kw):
    return api.put(f"/api/v1/processos/{ID}/formulario", json=corpo,
                   headers={**_auth(emissor, **kw), "If-Match": f'"{versao}"'})


def test_ler_traz_campos_valores_e_o_que_seria_descartado(api, emissor, banco):
    banco.responder("GET", "processos", 200, [_linha(
        dados={**COMPLETO}, documentos={"dfd": "DFD pronto", "etp": "ETP pronto"}, aprovados=["dfd"])])
    cab = _auth(emissor)
    r = api.get(f"/api/v1/processos/{ID}/formulario", headers=cab)
    assert r.status_code == 200
    corpo = r.json()
    assert len(corpo["campos"]) == 11
    assert {c["chave"] for c in corpo["campos"] if c["obrigatorio"]} >= {"orgao", "objeto", "itens"}
    assert corpo["valores"]["orgao"] == "Secretaria de Saúde"
    # A planilha volta calculada pelo MESMO `planilha.calcular` do wizard.
    assert corpo["itens"][0]["valor_total"] == 255.0
    assert corpo["valor_estimado"] == 255.0
    assert corpo["a_descartar"] == ["DFD", "ETP"]
    assert corpo["faltantes"] == []
    assert r.headers["ETag"] == f'"{VERSAO}"'
    assert banco.chamadas[-1].headers["authorization"] == cab["Authorization"]


def test_gravar_sem_if_match_e_428(api, emissor):
    r = api.put(f"/api/v1/processos/{ID}/formulario", json={"valores": COMPLETO}, headers=_auth(emissor))
    assert r.status_code == 428


def test_versao_velha_e_409_sem_gravar(api, emissor, banco):
    banco.responder("GET", "processos", 200, [_linha(atualizado_em=NOVA)])
    r = _put(api, emissor, {"valores": COMPLETO})
    assert r.status_code == 409 and r.json()["code"] == "VERSION_CONFLICT"
    assert not any(c.method == "PATCH" for c in banco.chamadas)


def test_quem_nao_e_dono_nem_admin_e_403(api, emissor, banco):
    banco.responder("GET", "processos", 200, [_linha(auth_user_id="outra-pessoa")])
    assert _put(api, emissor, {"valores": COMPLETO}).status_code == 403
    assert not any(c.method == "PATCH" for c in banco.chamadas)


def test_mudar_com_documento_exige_confirmar_o_descarte(api, emissor, banco):
    banco.responder("GET", "processos", 200, [_linha(
        dados={**COMPLETO}, documentos={"dfd": "DFD pronto"}, aprovados=["dfd"], etapa=2)])
    r = _put(api, emissor, {"valores": {**COMPLETO, "objeto": "Aquisição de luvas nitrílicas"}})
    assert r.status_code == 409
    assert r.json()["code"] == "DESCARTE_PENDENTE"
    assert "DFD" in r.json()["message"]
    assert not any(c.method == "PATCH" for c in banco.chamadas)


def test_descarte_confirmado_grava_a_cadeia_limpa_com_a_trava(api, emissor, banco):
    banco.responder("GET", "processos", 200, [_linha(
        dados={**COMPLETO, "_fluxo_mapa_riscos": True, "estimativa_pesquisa": {"x": 1}},
        documentos={"dfd": "DFD", "edital": "E", "arp": "A"}, aprovados=["dfd"], etapa=3)])
    banco.responder("PATCH", "processos", 200, [_linha(atualizado_em=NOVA, etapa=3,
                                                       dados={**COMPLETO, "objeto": "Novo objeto"})])
    r = _put(api, emissor, {"valores": {**COMPLETO, "objeto": "Novo objeto"}, "confirmar_descarte": True})
    assert r.status_code == 200, r.text
    assert set(r.json()["descartados"]) >= {"DFD"} and r.json()["mudou"] is True
    patch = next(c for c in banco.chamadas if c.method == "PATCH")
    assert patch.url.params["atualizado_em"] == f"eq.{VERSAO}"
    enviado = banco.corpo(patch)
    assert enviado["documentos"] == {} and enviado["aprovados"] == []
    assert enviado["objeto"] == "Novo objeto" and enviado["dados"]["objeto"] == "Novo objeto"
    # O que não é do formulário fica: fluxo do mapa e o que a pesquisa deixou.
    assert enviado["dados"]["_fluxo_mapa_riscos"] is True
    assert enviado["dados"]["estimativa_pesquisa"] == {"x": 1}
    assert enviado["dados"]["valor_estimado"] == 255.0
    assert r.headers["ETag"] == f'"{NOVA}"'


def test_salvar_sem_mexer_nao_descarta_nada(api, emissor, banco):
    # Processo antigo com quantidade em texto e sem valor_total: abrir e
    # salvar igual não pode contar como alteração.
    banco.responder("GET", "processos", 200, [_linha(dados={**COMPLETO}, documentos={"dfd": "DFD"},
                                                     aprovados=["dfd"], etapa=2)])
    banco.responder("PATCH", "processos", 200, [_linha(atualizado_em=NOVA, dados={**COMPLETO},
                                                       documentos={"dfd": "DFD"}, aprovados=["dfd"])])
    r = _put(api, emissor, {"valores": COMPLETO})
    assert r.status_code == 200, r.text
    assert r.json()["mudou"] is False and r.json()["descartados"] == []
    enviado = banco.corpo(next(c for c in banco.chamadas if c.method == "PATCH"))
    assert enviado["documentos"] == {"dfd": "DFD"} and enviado["aprovados"] == ["dfd"]


def test_iniciar_com_obrigatorio_vazio_e_422_e_nao_grava(api, emissor, banco):
    banco.responder("GET", "processos", 200, [_linha()])
    r = _put(api, emissor, {"valores": {"orgao": "Secretaria", "objeto": "Luvas"}, "iniciar": True})
    assert r.status_code == 422
    assert "Preencha os campos obrigatórios" in r.json()["message"]
    assert not any(c.method == "PATCH" for c in banco.chamadas)


def test_iniciar_completo_leva_a_etapa_a_1(api, emissor, banco):
    banco.responder("GET", "processos", 200, [_linha()])
    banco.responder("PATCH", "processos", 200, [_linha(atualizado_em=NOVA, etapa=1, dados={**COMPLETO})])
    r = _put(api, emissor, {"valores": COMPLETO, "iniciar": True})
    assert r.status_code == 200, r.text
    assert banco.corpo(next(c for c in banco.chamadas if c.method == "PATCH"))["etapa"] == 1


@pytest.mark.parametrize("corpo", [
    {"valores": {**COMPLETO, "tenant_id": "outro"}},
    {"valores": COMPLETO, "tenant_id": "outro"},
    {"valores": {**COMPLETO, "modelo_execucao": "Inventado"}},
    {"valores": {**COMPLETO, "orgao": "x" * 501}},
    {"valores": {**COMPLETO, "itens": "não é lista"}},
])
def test_entrada_invalida_e_422(api, emissor, banco, corpo):
    banco.responder("GET", "processos", 200, [_linha()])
    assert _put(api, emissor, corpo).status_code == 422
    assert not any(c.method == "PATCH" for c in banco.chamadas)


def test_modelo_de_planilha_exige_sessao_e_devolve_xlsx(api, emissor):
    assert api.get("/api/v1/processos/modelo-planilha.xlsx").status_code == 401
    r = api.get("/api/v1/processos/modelo-planilha.xlsx", headers=_auth(emissor))
    assert r.status_code == 200 and r.content.startswith(b"PK")
    assert r.headers["content-type"].startswith(XLSX)


def _xlsx() -> bytes:
    livro = Workbook()
    folha = livro.active
    folha.append(["Código", "Descrição", "Unidade", "Quantidade", "Valor unitário"])
    folha.append(["1", "Luva de procedimento", "CX", 10, 25.5])
    saida = io.BytesIO()
    livro.save(saida)
    return saida.getvalue()


def test_planilha_lida_nao_grava(api, emissor, banco):
    banco.responder("GET", "processos", 200, [_linha()])
    r = api.post(f"/api/v1/processos/{ID}/formulario/planilha", content=_xlsx(),
                 headers={**_auth(emissor), "Content-Type": XLSX})
    assert r.status_code == 200, r.text
    assert r.json()["itens"][0]["descricao"] == "Luva de procedimento"
    assert r.json()["valor_estimado"] == 255.0
    assert not any(c.method == "PATCH" for c in banco.chamadas)


def test_planilha_de_outro_tipo_e_415(api, emissor):
    r = api.post(f"/api/v1/processos/{ID}/formulario/planilha", content=b"a,b",
                 headers={**_auth(emissor), "Content-Type": "text/csv"})
    assert r.status_code == 415


def test_memorando_em_texto_e_extraido(api, emissor, banco):
    banco.responder("GET", "processos", 200, [_linha()])
    texto = "Memorando nº 12/2026 — solicito a aquisição de luvas para as unidades de saúde."
    r = api.post(f"/api/v1/processos/{ID}/formulario/memorando?nome=memorando.txt",
                 content=texto.encode(), headers={**_auth(emissor), "Content-Type": "text/plain"})
    assert r.status_code == 200, r.text
    assert r.json()["texto"].startswith("Memorando nº 12/2026")


def test_memorando_de_formato_nao_suportado_e_415(api, emissor):
    r = api.post(f"/api/v1/processos/{ID}/formulario/memorando?nome=planilha.exe", content=b"x",
                 headers={**_auth(emissor), "Content-Type": "application/octet-stream"})
    assert r.status_code == 415


def test_processo_de_outro_municipio_e_404(api, emissor, banco):
    banco.responder("GET", "processos", 200, [])
    assert api.get(f"/api/v1/processos/{ID}/formulario", headers=_auth(emissor)).status_code == 404
