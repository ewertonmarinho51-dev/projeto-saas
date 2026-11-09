"""
Análise antes da aprovação e decisões da contratação.

O motor de regras, o validador, os achados e a nota de qualidade são os
reais: só a projeção nativa (Node/WASM) e o banco são substituídos. O que se
prova é o que este módulo promete: cada motivo de recusa aparece, as
decisões ausentes viram perguntas, a resposta vira fato confirmado com fonte
humana, e a sincronização com o formulário não a apaga.
"""

from __future__ import annotations

import json
from types import SimpleNamespace

import httpx
import pytest
from fastapi.testclient import TestClient

from govconect_api import analise_documental as ad, documentos_nativos as dn
from govconect_api.config import carregar
from govconect_api.main import criar_app
from govconect_api.verificador import VerificadorSupabase
from src import conhecimento, db, fatos as fatos_mod
from src import wordcraft_blocos

from apoio_jwt import EMISSOR, Emissor, PostgrestFalso

PROCESSO = "cccccccc-0000-4000-8000-0000000000f1"
DFD = dn.id_do_documento(PROCESSO, "dfd")
AMBIENTE = {"APP_ENV": "test", "SUPABASE_URL": "https://exemplo-staging.supabase.co",
            "SUPABASE_KEY": "chave-publicavel-de-teste", "GOVCONECT_WORDCRAFT_WORKSPACE": "on"}
DADOS = {"objeto": "Gêneros alimentícios", "modelo_execucao": "Sistema de Registro de Preços (SRP)"}
URL = f"/api/v1/processos/{PROCESSO}/documentos/{DFD}/analise"


def _fato(path, valor, fonte="formulario:x", status="confirmado", tipo="texto", **extra):
    return {"id": f"id-{path}", "processo_id": PROCESSO, "path": path, "valor": valor, "tipo": tipo,
            "fonte": fonte, "status": status, "confianca": 0.9, "versao": 1, **extra}


class Banco(PostgrestFalso):
    def __init__(self):
        super().__init__()
        self.rpcs: list[dict] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        caminho = request.url.path
        if caminho.endswith("/processos"):
            self.chamadas.append(request)
            return httpx.Response(200, json=[{"id": PROCESSO, "dados": DADOS}])
        if caminho.endswith("/rpc/fatos_canonicos_transicionar"):
            self.chamadas.append(request)
            self.rpcs.append(json.loads(request.content))
            return httpx.Response(204)
        return super().__call__(request)


class Servico:
    _native = {}

    def __init__(self, texto="1. INFORMAÇÕES GERAIS\n\nTexto do DFD.", indice=True):
        self.texto, self.indice = texto, indice

    def abrir(self, document_id):
        return SimpleNamespace(tipo="dfd", payload=b"x", index=object() if self.indice else None,
                               revision=8, content_hash="a" * 64)


@pytest.fixture
def emissor():
    return Emissor()


@pytest.fixture
def estado(monkeypatch):
    s = SimpleNamespace(fatos=[_fato("objeto.descricao", "Gêneros"), _fato("procedimento.srp", True, tipo="booleano")],
                        salvos=[])

    def listar(pid, apenas_vigentes=True):
        return [f for f in s.fatos if not apenas_vigentes or f["status"] != "substituido"]

    def salvar(novos):
        for i, f in enumerate(novos):
            s.fatos.append({**f, "id": f"novo-{len(s.salvos)}-{i}"})
        s.salvos.extend(novos)
        return novos

    monkeypatch.setattr(db, "listar_fatos", listar)
    monkeypatch.setattr(db, "salvar_fatos", salvar)
    monkeypatch.setattr(db, "listar_regras", lambda apenas_publicadas=True: [])
    monkeypatch.setattr(db, "flag_ativa", lambda nome: False)
    monkeypatch.setattr(db, "obter_config", lambda chave: "")
    monkeypatch.setattr(conhecimento, "fontes_revogadas_do_banco", lambda: set())
    monkeypatch.setattr(dn.contexto, "modulo_em_rollout_aqui", lambda modulo: True)
    return s


@pytest.fixture
def projecao(monkeypatch):
    def projetar(tipo, payload, *, indice, **_):
        texto = api_servico.texto
        return SimpleNamespace(blocos=[SimpleNamespace(tipo="titulo", conteudo="1. INFORMAÇÕES GERAIS"),
                                       SimpleNamespace(tipo="paragrafo", conteudo="Texto do DFD.")],
                               apto_analise=True, texto_analise=texto)

    api_servico = Servico()
    monkeypatch.setattr(wordcraft_blocos, "projetar_documento", projetar)
    return api_servico


def _api(emissor, servico, banco=None, ambiente=AMBIENTE):
    banco = banco or Banco()
    rest = banco.cliente()
    app = criar_app(carregar(ambiente), rest=rest,
                    verificador=VerificadorSupabase(emissor=EMISSOR, rest=rest, chave_para=emissor.chave_para))
    app.state.motor_documental = dn.Motor(servico, "https://x", "https://x/m.js", "https://x/m.wasm")
    return TestClient(app, raise_server_exceptions=False), banco


def _h(emissor):
    return {"Authorization": f"Bearer {emissor.token()}"}


# ---------------------------------------------------------------------------
# Análise
# ---------------------------------------------------------------------------
def test_dado_que_ninguem_perguntou_vira_decisao_e_recusa(emissor, estado, projecao):
    api, _ = _api(emissor, projecao)
    corpo = api.get(URL, headers=_h(emissor)).json()
    assert corpo["pode_aprovar"] is False and corpo["revisao"] == 8
    caminhos = {d["path"] for d in corpo["decisoes"]}
    assert {"contratacao.garantia_exigida", "contratacao.amostra_exigida", "objeto.natureza"} <= caminhos
    assert any("decisão" in m for m in corpo["motivos"])
    assert corpo["estrutura"] == ["1. INFORMAÇÕES GERAIS"]


def test_decidido_some_das_perguntas(emissor, estado, projecao):
    for path, valor, tipo in (("contratacao.garantia_exigida", False, "booleano"),
                              ("contratacao.amostra_exigida", False, "booleano"),
                              ("procedimento.dedicacao_mao_de_obra", False, "booleano"),
                              ("objeto.natureza", "BENS", "texto"), ("objeto.categoria", "ALIMENTOS", "texto")):
        estado.fatos.append(_fato(path, valor, fonte=ad.FONTE_DA_DECISAO, tipo=tipo))
    api, _ = _api(emissor, projecao)
    corpo = api.get(URL, headers=_h(emissor)).json()
    assert corpo["decisoes"] == []
    assert not any("decisão" in m for m in corpo["motivos"])


def test_campo_a_preencher_aparece_como_motivo(emissor, estado, projecao):
    projecao.texto = "1. INFORMAÇÕES GERAIS\n\nResponsável: [PREENCHER: matrícula do responsável]."
    api, _ = _api(emissor, projecao)
    motivos = api.get(URL, headers=_h(emissor)).json()["motivos"]
    assert any("matrícula do responsável" in m for m in motivos)


def test_fato_sem_confirmacao_e_motivo(emissor, estado, projecao):
    estado.fatos.append(_fato("prazo.descricao", "março", status="extraido"))
    api, _ = _api(emissor, projecao)
    assert any("sem confirmação" in m for m in api.get(URL, headers=_h(emissor)).json()["motivos"])


def test_revisao_sem_indice_nao_finge_que_analisou(emissor, estado):
    api, _ = _api(emissor, Servico(indice=False))
    corpo = api.get(URL, headers=_h(emissor)).json()
    assert corpo["pode_aprovar"] is False and corpo["estrutura"] == []
    assert any("índice do motor" in m for m in corpo["motivos"])


def test_sem_canario_a_analise_nao_existe(emissor, estado, projecao):
    api, _ = _api(emissor, projecao, ambiente={**AMBIENTE, "GOVCONECT_WORDCRAFT_WORKSPACE": ""})
    assert api.get(URL, headers=_h(emissor)).status_code == 404


def test_documento_de_outro_processo_e_404(emissor, estado, projecao):
    api, _ = _api(emissor, projecao)
    outro = dn.id_do_documento("cccccccc-0000-4000-8000-0000000000f2", "dfd")
    assert api.get(f"/api/v1/processos/{PROCESSO}/documentos/{outro}/analise", headers=_h(emissor)).status_code == 404


# ---------------------------------------------------------------------------
# Decisões
# ---------------------------------------------------------------------------
DECISOES = f"/api/v1/processos/{PROCESSO}/decisoes"


@pytest.mark.parametrize("respostas", [
    {"objeto.descricao": "outra"},                 # não é decisão desta tela
    {"objeto.natureza": "QUALQUER"},               # fora das opções
    {"contratacao.garantia_exigida": "Sim"},       # booleano em texto
])
def test_decisao_fora_do_vocabulario_e_recusada(emissor, estado, projecao, respostas):
    api, banco = _api(emissor, projecao)
    assert api.post(DECISOES, headers=_h(emissor), json={"respostas": respostas}).status_code == 422
    assert estado.salvos == [] and banco.rpcs == []


def test_decisao_vira_fato_confirmado_com_fonte_humana(emissor, estado, projecao):
    api, banco = _api(emissor, projecao)
    r = api.post(DECISOES, headers=_h(emissor),
                 json={"respostas": {"contratacao.garantia_exigida": False, "objeto.natureza": "BENS"}})
    assert r.status_code == 200 and r.json() == {"registradas": 2}, r.text
    assert {f["path"] for f in estado.salvos} == {"contratacao.garantia_exigida", "objeto.natureza"}
    assert all(f["fonte"] == ad.FONTE_DA_DECISAO and f["confianca"] == 1.0 for f in estado.salvos)
    # Confirmação pela RPC da 0037, com o JWT de quem decidiu.
    assert len(banco.rpcs) == 1 and len(banco.rpcs[0]["p_confirmar"]) == 2


def test_mudar_a_decisao_substitui_sem_apagar(emissor, estado, projecao):
    estado.fatos.append(_fato("contratacao.garantia_exigida", False, fonte=ad.FONTE_DA_DECISAO, tipo="booleano"))
    api, banco = _api(emissor, projecao)
    api.post(DECISOES, headers=_h(emissor), json={"respostas": {"contratacao.garantia_exigida": True}})
    assert banco.rpcs[0]["p_substituir"] == ["id-contratacao.garantia_exigida"]
    assert estado.salvos[0]["versao"] == 2


def test_quem_nao_pode_inserir_recebe_403(emissor, estado, projecao, monkeypatch):
    monkeypatch.setattr(db, "salvar_fatos", lambda novos: (_ for _ in ()).throw(db.ErroBanco("42501")))
    api, banco = _api(emissor, projecao)
    r = api.post(DECISOES, headers=_h(emissor), json={"respostas": {"objeto.natureza": "BENS"}})
    assert r.status_code == 403 and banco.rpcs == []


def test_sincronizar_o_formulario_nao_troca_a_decisao_humana():
    existentes = [_fato("objeto.natureza", "SERVICOS", fonte=ad.FONTE_DA_DECISAO)]
    dados = {"objeto": "Reforma do prédio", "modelo_execucao": "Obra / serviço de engenharia"}
    extraidos = dn.extraidos_sem_decisao(dados, PROCESSO, existentes)
    assert "objeto.natureza" not in {f["path"] for f in extraidos}
    # Dente: sem a decisão, o formulário emitiria a natureza.
    assert "objeto.natureza" in {f["path"] for f in fatos_mod.extrair_do_formulario(dados, PROCESSO)}


def test_as_categorias_oferecidas_existem_no_vocabulario_do_motor():
    oferecidas = {o["valor"] for o in ad.DECISOES["objeto.categoria"]["opcoes"]} - {"OUTRA"}
    assert oferecidas <= set(fatos_mod.CATEGORIAS_OBJETO)


def test_toda_decisao_oferecida_e_lida_por_uma_regra_base():
    lidos = json.dumps(conhecimento.regras_base(), ensure_ascii=False)
    assert all(path in lidos for path in ad.DECISOES)
