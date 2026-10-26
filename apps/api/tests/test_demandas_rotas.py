"""
Consolidar Demandas (M4) contra um PostgREST SIMULADO. PDFs de verdade,
gerados na hora com o pymupdf (o mesmo jeito das provas do domínio).
"""

import base64

import pytest
from fastapi.testclient import TestClient

from govconect_api import demandas as rotas_demandas
from govconect_api.config import carregar
from govconect_api.main import criar_app
from govconect_api.verificador import VerificadorSupabase

from apoio_jwt import EMISSOR, SECRETARIA_A, USUARIO_A, Emissor, PostgrestFalso

ID = "cccccccc-0000-4000-8000-000000000001"
VERSAO = "2026-10-22T14:00:00.123456+00:00"
NOVA = "2026-10-22T14:05:00.000000+00:00"


def _pdf(texto: str) -> bytes:
    import pymupdf

    doc = pymupdf.open()
    pagina = doc.new_page()
    pagina.insert_textbox(pymupdf.Rect(40, 40, 560, 780), texto, fontsize=9)
    dados = doc.tobytes()
    doc.close()
    return dados


def _quadro(numero: str, orgao: str, linhas: str) -> str:
    return (f"DOCUMENTO DE FORMALIZAÇÃO DE DEMANDA Nº {numero}\nÓRGÃO :\n05  {orgao}\n"
            f"Código Quant Unidade Descrição\n{linhas}")


SEMEC = _quadro("20260101001", "Secretaria de Educação",
                "370614 ENVELOPE AMARELO 260MMX360MM 50,0000 UNIDADE\n133975 PAPEL VERGE CORES VARIADAS 30,0000 PACOTE\n")
SEMSA = _quadro("20260101002", "Secretaria de Saúde",
                "370614 ENVELOPE AMARELO 260MMX360MM 20,0000 UNIDADE\n")
CONFLITO = _quadro("20260101003", "Secretaria de Saúde", "133975 PAPEL VERGE CORES VARIADAS 2,0000 CAIXA\n")


def _arquivo(nome: str, texto: str) -> dict:
    return {"nome": nome, "conteudo": base64.b64encode(_pdf(texto)).decode()}


def _linha(**extra):
    base = {"id": ID, "nome": "", "orgao": "Prefeitura", "objeto": "Material de expediente", "etapa": 0,
            "dados": {"orgao": "Prefeitura", "objeto": "Material de expediente",
                      "itens": [{"codigo": "1", "descricao": "Caneta", "unidade": "UN",
                                 "quantidade": 5, "valor_unitario": 2}]},
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
def modulo(monkeypatch):
    estado = {"ligado": True}
    monkeypatch.setattr(rotas_demandas.contexto, "modulo_disponivel_aqui", lambda _m: estado["ligado"])
    return estado


@pytest.fixture
def api(emissor, banco, modulo):
    config = carregar({"APP_ENV": "test", "SUPABASE_URL": "https://exemplo-staging.supabase.co",
                       "SUPABASE_KEY": "chave-publicavel-de-teste"})
    rest = banco.cliente()
    verificador = VerificadorSupabase(emissor=EMISSOR, rest=rest, chave_para=emissor.chave_para)
    return TestClient(criar_app(config, verificador=verificador, rest=rest), raise_server_exceptions=False)


def _auth(emissor, **kw):
    return {"Authorization": f"Bearer {emissor.token(**kw)}"}


def test_modulos_diz_o_que_esta_ligado(api, emissor, modulo):
    assert api.get("/api/v1/modulos", headers=_auth(emissor)).json() == {"consolidar_demandas": True}
    modulo["ligado"] = False
    assert api.get("/api/v1/modulos", headers=_auth(emissor)).json() == {"consolidar_demandas": False}


def test_modulo_desligado_e_404(api, emissor, banco, modulo):
    modulo["ligado"] = False
    r = api.post(f"/api/v1/processos/{ID}/demandas/consolidacao", headers=_auth(emissor),
                 json={"arquivos": [_arquivo("a.pdf", SEMEC)]})
    assert r.status_code == 404 and r.json()["code"] == "MODULE_UNAVAILABLE"


def test_consolida_soma_por_codigo_e_secretaria(api, emissor, banco):
    banco.responder("GET", "processos", 200, [_linha()])
    r = api.post(f"/api/v1/processos/{ID}/demandas/consolidacao", headers=_auth(emissor),
                 json={"arquivos": [_arquivo("semec.pdf", SEMEC), _arquivo("semsa.pdf", SEMSA)]})
    assert r.status_code == 200, r.text
    corpo = r.json()
    assert corpo["fecha"] is True and corpo["conflitos"] == []
    envelope = next(l for l in corpo["linhas"] if l["codigo"] == "370614")
    assert envelope["total"] == "70"
    assert sorted(envelope["por_secretaria"].values()) == ["20", "50"]
    assert "50" in envelope["explicacao"]
    assert [a["status"] for a in corpo["arquivos"]] == ["lido", "lido"]


def test_arquivo_que_nao_e_pdf_vira_erro_visivel(api, emissor, banco):
    banco.responder("GET", "processos", 200, [_linha()])
    r = api.post(f"/api/v1/processos/{ID}/demandas/consolidacao", headers=_auth(emissor),
                 json={"arquivos": [_arquivo("semec.pdf", SEMEC),
                                    {"nome": "planilha.xlsx", "conteudo": base64.b64encode(b"PK\x03\x04").decode()}]})
    assert r.status_code == 200
    assert r.json()["erros"] == [{"nome": "planilha.xlsx", "mensagem": "Não é um PDF."}]


def test_conflito_de_unidade_bloqueia_aplicar_ate_ser_aceito(api, emissor, banco):
    arquivos = [_arquivo("semec.pdf", SEMEC), _arquivo("conflito.pdf", CONFLITO)]
    banco.responder("GET", "processos", 200, [_linha()])
    corpo = api.post(f"/api/v1/processos/{ID}/demandas/consolidacao", headers=_auth(emissor),
                     json={"arquivos": arquivos}).json()
    assert [c["codigo"] for c in corpo["conflitos"]] == ["133975"]

    banco.responder("GET", "processos", 200, [_linha()])
    r = api.put(f"/api/v1/processos/{ID}/demandas/aplicacao",
                headers={**_auth(emissor), "If-Match": f'"{VERSAO}"'}, json={"arquivos": arquivos})
    assert r.status_code == 422 and "conflito de unidade" in r.json()["message"]
    assert not any(c.method == "PATCH" for c in banco.chamadas)


def test_aplicar_grava_a_planilha_e_a_procedencia(api, emissor, banco):
    banco.responder("GET", "processos", 200, [_linha()])
    banco.responder("PATCH", "processos", 200, [_linha(atualizado_em=NOVA)])
    r = api.put(f"/api/v1/processos/{ID}/demandas/aplicacao",
                headers={**_auth(emissor), "If-Match": f'"{VERSAO}"'},
                json={"arquivos": [_arquivo("semec.pdf", SEMEC), _arquivo("semsa.pdf", SEMSA)]})
    assert r.status_code == 200, r.text
    assert r.json()["itens"] == 2 and r.json()["versao"] == NOVA
    patch = next(c for c in banco.chamadas if c.method == "PATCH")
    assert patch.url.params["atualizado_em"] == f"eq.{VERSAO}"
    dados = banco.corpo(patch)["dados"]
    envelope = next(i for i in dados["itens"] if i["codigo"] == "370614")
    assert envelope["quantidade"] == 70.0 and envelope["valor_unitario"] in ("", 0, 0.0)
    assert dados["consolidacao_demanda"]["por_item"]["370614|UNIDADE"]["total"] == "70"
    assert dados["objeto"] == "Material de expediente"   # o resto do formulário fica


def test_aplicar_com_documento_exige_confirmar_o_descarte(api, emissor, banco):
    banco.responder("GET", "processos", 200, [_linha(documentos={"dfd": "DFD"}, aprovados=["dfd"])])
    r = api.put(f"/api/v1/processos/{ID}/demandas/aplicacao",
                headers={**_auth(emissor), "If-Match": f'"{VERSAO}"'},
                json={"arquivos": [_arquivo("semec.pdf", SEMEC)]})
    assert r.status_code == 409 and r.json()["code"] == "DESCARTE_PENDENTE"
    assert not any(c.method == "PATCH" for c in banco.chamadas)


def test_aplicar_exige_dono_ou_admin_e_versao(api, emissor, banco):
    banco.responder("GET", "processos", 200, [_linha(auth_user_id="outra")])
    r = api.put(f"/api/v1/processos/{ID}/demandas/aplicacao",
                headers={**_auth(emissor), "If-Match": f'"{VERSAO}"'},
                json={"arquivos": [_arquivo("semec.pdf", SEMEC)]})
    assert r.status_code == 403
    banco.responder("GET", "processos", 200, [_linha(atualizado_em=NOVA)])
    r = api.put(f"/api/v1/processos/{ID}/demandas/aplicacao",
                headers={**_auth(emissor), "If-Match": f'"{VERSAO}"'},
                json={"arquivos": [_arquivo("semec.pdf", SEMEC)]})
    assert r.status_code == 409 and r.json()["code"] == "VERSION_CONFLICT"
    assert api.put(f"/api/v1/processos/{ID}/demandas/aplicacao", headers=_auth(emissor),
                   json={"arquivos": [_arquivo("semec.pdf", SEMEC)]}).status_code == 428


def test_planilha_consolidada_em_xlsx(api, emissor, banco):
    banco.responder("GET", "processos", 200, [_linha()])
    r = api.post(f"/api/v1/processos/{ID}/demandas/planilha", headers=_auth(emissor),
                 json={"arquivos": [_arquivo("semec.pdf", SEMEC)]})
    assert r.status_code == 200 and r.content.startswith(b"PK")


def test_base64_corrompido_e_422(api, emissor, banco):
    banco.responder("GET", "processos", 200, [_linha()])
    r = api.post(f"/api/v1/processos/{ID}/demandas/consolidacao", headers=_auth(emissor),
                 json={"arquivos": [{"nome": "a.pdf", "conteudo": "%%%não-base64%%%"}]})
    assert r.status_code == 422


@pytest.mark.parametrize("extra", [{"tenant_id": "x"}, {"papel": "admin"}])
def test_identidade_no_corpo_e_recusada(api, emissor, banco, extra):
    r = api.post(f"/api/v1/processos/{ID}/demandas/consolidacao", headers=_auth(emissor),
                 json={"arquivos": [_arquivo("semec.pdf", SEMEC)], **extra})
    assert r.status_code == 422
