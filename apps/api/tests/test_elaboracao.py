"""
Elaboração automática: rotas, worker e o caminho real do domínio até o motor.

O banco é falso, mas guarda estado: `processos` tem CAS em `atualizado_em` e
`api_jobs` recusa o segundo job ativo, como o índice da 0039. O motor de IA é
o único ponto substituído no domínio: prompt, tabela de itens e validação
rodam de verdade, sem o Streamlit. O ciclo com banco, fila e worker reais
está em `apps/web/e2e/elaboracao.spec.ts`.
"""

from __future__ import annotations

import json
import time
import uuid
from datetime import datetime, timedelta, timezone

import httpx
import pytest
from fastapi.testclient import TestClient

from govconect_api import coleta, documentos_nativos as dn, elaboracao as el
from govconect_api.config import carregar
from govconect_api.main import criar_app
from govconect_api.verificador import VerificadorSupabase
from src import db, llm, rag
from src import elaboracao as dominio
from src import familias as familias_mod
from src.config import CHAVE_FLUXO_MAPA, CAMPOS_FORMULARIO

from apoio_jwt import EMISSOR, TENANT_A, USUARIO_A, Emissor, PostgrestFalso

PROCESSO = "cccccccc-0000-4000-8000-0000000000e1"
OUTRO_USUARIO = "bbbbbbbb-0000-4000-8000-00000000b001"
AMBIENTE = {"APP_ENV": "test", "SUPABASE_URL": "https://exemplo-staging.supabase.co",
            "SUPABASE_KEY": "chave-publicavel-de-teste", "GOVCONECT_WORDCRAFT_WORKSPACE": "on"}
TEXTO_DA_IA = "# DFD\n\n1. Necessidade da contratação redigida pelo motor.\n\n[[TABELA_ITENS]]\n"


def _completos() -> dict:
    dados = {"orgao": "Secretaria de Administração", "objeto": "Papel A4 sintético"}
    for chave, meta in CAMPOS_FORMULARIO.items():
        if meta["obrigatorio"] and chave != "itens":
            dados.setdefault(chave, "Preenchido")
    dados["itens"] = [{"descricao": "Papel A4", "unidade": "resma", "quantidade": "10",
                       "valor_unitario": "30,00"}]
    return dados


def _agora(segundos=0) -> str:
    return (datetime.now(timezone.utc) + timedelta(seconds=segundos)).isoformat()


class Banco(PostgrestFalso):
    """`processos`, `documentos_editor` e `api_jobs` com estado."""

    def __init__(self) -> None:
        super().__init__()
        self.processo = {"id": PROCESSO, "nome": "", "orgao": "Secretaria", "objeto": "Papel", "etapa": 1,
                         "dados": _completos(), "documentos": {}, "aprovados": [],
                         "criado_em": _agora(-60), "atualizado_em": _agora(-30),
                         "secretaria_id": None, "auth_user_id": USUARIO_A, "idempotency_key": "x"}
        self.cabecas: list[dict] = []
        self.jobs: list[dict] = []
        self.versoes = 0

    def _filtrar_jobs(self, request):
        q = request.url.params
        linhas = self.jobs
        for campo in ("id", "tipo", "recurso_id"):
            if q.get(campo):
                linhas = [j for j in linhas if str(j[campo]) == q[campo].removeprefix("eq.")]
        if q.get("estado", "").startswith("in."):
            linhas = [j for j in linhas if j["estado"] in ("queued", "running")]
        return sorted(linhas, key=lambda j: j["criado_em"], reverse=True)

    def __call__(self, request: httpx.Request) -> httpx.Response:
        tabela = request.url.path.rsplit("/", 1)[-1]
        fila = self.respostas.get((request.method, tabela))
        if tabela not in ("processos", "documentos_editor", "api_jobs") or fila:
            return super().__call__(request)
        self.chamadas.append(request)
        if tabela == "documentos_editor":
            return httpx.Response(200, json=self.cabecas)
        if tabela == "processos":
            if request.method == "GET":
                return httpx.Response(200, json=[self.processo])
            if request.url.params.get("atualizado_em") != f"eq.{self.processo['atualizado_em']}":
                return httpx.Response(200, json=[])
            self.processo.update(json.loads(request.content))
            self.versoes += 1
            self.processo["atualizado_em"] = _agora(self.versoes)
            return httpx.Response(200, json=[self.processo])
        if request.method == "GET":
            return httpx.Response(200, json=self._filtrar_jobs(request))
        if request.method == "POST":
            novo = json.loads(request.content)
            if any(j["estado"] in ("queued", "running") and j["auth_user_id"] == novo["auth_user_id"]
                   and j["recurso_id"] == novo["recurso_id"] for j in self.jobs):
                return httpx.Response(409, json={"code": "23505", "message": "duplicada"})
            linha = {"id": str(uuid.uuid4()), "estado": "queued", "feitos": 0, "tentativas": 0, "erro_codigo": "",
                     "criado_em": _agora(), "atualizado_em": _agora(), "iniciado_em": None, "concluido_em": None,
                     **novo}
            self.jobs.append(linha)
            return httpx.Response(201, json=[linha])
        alvo = self._filtrar_jobs(request)
        for linha in alvo:
            linha.update(json.loads(request.content), atualizado_em=_agora())
        return httpx.Response(200, json=alvo)


class FilaFalsa:
    def __init__(self, quebrar=False):
        self.avisos, self.quebrar = [], quebrar

    def enfileirar(self, **aviso):
        if self.quebrar:
            raise ConnectionError("redis fora")
        self.avisos.append(aviso)


class Servico:
    def __init__(self):
        self.lidos = []

    def texto_aprovado(self, document_id):
        self.lidos.append(document_id)
        return "dfd", "Texto aprovado do DFD no editor."


@pytest.fixture
def emissor():
    return Emissor()


@pytest.fixture
def banco():
    return Banco()


@pytest.fixture
def fila():
    return FilaFalsa()


@pytest.fixture
def flags(monkeypatch):
    ligadas = set()
    monkeypatch.setattr(db, "flag_ativa", lambda nome: nome in ligadas)
    monkeypatch.setattr(db, "obter_config", lambda chave: "")
    monkeypatch.setattr(dn.contexto, "modulo_em_rollout_aqui", lambda modulo: modulo == dn.FLAG_CANARIO)
    return ligadas


@pytest.fixture
def api(emissor, banco, fila, flags):
    return _montar(emissor, banco, fila)


def _montar(emissor, banco, fila, ambiente=AMBIENTE):
    rest = banco.cliente()
    app = criar_app(carregar(ambiente), rest=rest, fila=fila, verificador=VerificadorSupabase(
        emissor=EMISSOR, rest=rest, chave_para=emissor.chave_para))
    app.state.motor_documental = dn.Motor(Servico(), "https://x", "https://x/m.js", "https://x/m.wasm")
    return TestClient(app, raise_server_exceptions=False)


def _h(emissor, chave="elaboracao-0001", **kw):
    return {"Authorization": f"Bearer {emissor.token(**kw)}", "Idempotency-Key": chave}


URL = f"/api/v1/processos/{PROCESSO}/elaboracao"


def _rodar(banco, job_id, emissor):
    return el.processar_elaboracao(job_id=job_id, token=emissor.token(), tenant_id=TENANT_A,
                                   auth_user_id=USUARIO_A, secretaria_id=None, usuario_id="",
                                   rest=banco.cliente())


@pytest.fixture
def motor(monkeypatch):
    """Só o motor sai do jogo: `gerar_documento` e `validacao` rodam de verdade."""
    chamadas = []

    def responder(motor_, system_prompt, user_prompt, chave, **_):
        chamadas.append(user_prompt)
        llm._ultimo_uso.update(modelo="modelo-falso", tokens_entrada=1, tokens_saida=1)
        return TEXTO_DA_IA

    monkeypatch.setattr(llm, "motores_disponiveis", lambda: [("openai", "chave-falsa")])
    monkeypatch.setattr(llm, "_chamar_motor", responder)
    monkeypatch.setattr(rag, "montar_contexto", lambda dados, doc: {"bloco": "", "trace": {}})
    monkeypatch.setattr(db, "registrar_geracao_bd", lambda registro: None)
    return chamadas


# ---------------------------------------------------------------------------
# Domínio
# ---------------------------------------------------------------------------
def _situacao(tipo, situacao):
    return dominio.SituacaoDoDocumento(tipo, situacao)


def test_a_sequencia_nao_pula_documento_sem_aprovacao():
    docs = [_situacao("dfd", dominio.EM_REVISAO), _situacao("etp", dominio.PENDENTE)]
    assert dominio.proximo_passo(docs, []) == dominio.Proximo(dominio.REVISAR, "dfd")


def test_faltou_dado_o_proximo_passo_e_o_formulario():
    docs = [_situacao("dfd", dominio.PENDENTE)]
    assert dominio.proximo_passo(docs, ["Objeto"]) == dominio.Proximo(dominio.FORMULARIO)
    assert dominio.proximo_passo(docs, []) == dominio.Proximo(dominio.ELABORAR, "dfd")


def test_aprovado_em_tudo_conclui():
    assert dominio.proximo_passo([_situacao("dfd", dominio.APROVADO), _situacao("etp", dominio.EMITIDO)],
                                 []) == dominio.Proximo(dominio.CONCLUIDO)


def test_cabeca_nativa_manda_no_texto_legado():
    processo = {"dados": {}, "documentos": {"dfd": "texto"}, "aprovados": ["dfd"]}
    saida = dominio.situacoes(processo, {"dfd": {"status": "rascunho", "revision": 3}})
    assert saida[0] == dominio.SituacaoDoDocumento("dfd", dominio.EM_REVISAO, 3)


def test_a_flag_do_mapa_nao_reescreve_processo_com_cadeia():
    assert CHAVE_FLUXO_MAPA in dominio.com_fluxo({}, {}, True)
    assert CHAVE_FLUXO_MAPA not in dominio.com_fluxo({}, {"dfd": "x"}, True)


def test_rascunho_nao_entra_no_contexto(flags):
    processo = {"dados": {}, "documentos": {"dfd": "a", "etp": "b"}}
    contexto = dominio.contexto_para("tr", processo, {"dfd": "DFD aprovado"})
    assert "DFD aprovado" in contexto and "=== Estudo" not in contexto


def test_familia_ambigua_nao_vira_palpite(monkeypatch):
    monkeypatch.setattr(familias_mod, "resolver_para_processo", lambda *a, **k: {"situacao": "ambigua"})
    with pytest.raises(dominio.EscolhaDeFamilia):
        dominio.elaborar("dfd", {}, None, PROCESSO, lambda _e: None)


# ---------------------------------------------------------------------------
# Rotas
# ---------------------------------------------------------------------------
def test_sem_canario_a_rota_nao_existe(emissor, banco, fila, flags):
    api = _montar(emissor, banco, fila, {**AMBIENTE, "GOVCONECT_WORDCRAFT_WORKSPACE": ""})
    assert api.get(URL, headers=_h(emissor)).status_code == 404
    assert api.post(URL, headers=_h(emissor)).status_code == 404
    assert not banco.jobs


def test_conta_fora_da_lista_nao_elabora(emissor, banco, fila, flags):
    api = _montar(emissor, banco, fila, {**AMBIENTE, "GOVCONECT_WORDCRAFT_WORKSPACE_CONTAS": OUTRO_USUARIO})
    assert api.post(URL, headers=_h(emissor)).status_code == 404


def test_panorama_mostra_o_proximo_documento(api, emissor, flags):
    flags.add("mapa_riscos")
    corpo = api.get(URL, headers=_h(emissor)).json()
    assert [d["tipo"] for d in corpo["documentos"]] == ["dfd", "etp", "mapa_riscos", "tr", "edital"]
    assert corpo["proximo"] == {"acao": "elaborar", "tipo": "dfd", "sigla": "DFD"}
    assert corpo["job"] is None and corpo["faltantes"] == []


def test_faltou_obrigatorio_nao_gera(api, emissor, banco):
    banco.processo["dados"] = {"orgao": "x", "objeto": "y"}
    assert api.get(URL, headers=_h(emissor)).json()["proximo"]["acao"] == "formulario"
    r = api.post(URL, headers=_h(emissor))
    assert r.status_code == 422 and "Preencha os campos obrigatórios" in r.json()["message"]
    assert not banco.jobs


def test_pedir_grava_o_job_antes_da_fila_e_sem_token_no_job(api, emissor, banco, fila):
    r = api.post(URL, headers=_h(emissor), json={"tipo": "dfd"})
    assert r.status_code == 202, r.text
    corpo = r.json()
    assert corpo["estado"] == "queued" and corpo["resultado"]["documento"] == "dfd"
    assert corpo["total"] == len(dominio.ESTAGIOS)
    assert fila.avisos[0]["tarefa"] == "elaboracao" and fila.avisos[0]["job_id"] == corpo["id"]
    assert banco.jobs[0]["parametros"]["tipo"] == "dfd"
    assert "token" not in json.dumps(banco.jobs[0])


def test_clique_repetido_recebe_o_mesmo_job(api, emissor, banco, fila):
    primeiro = api.post(URL, headers=_h(emissor, "elaboracao-0001"))
    segundo = api.post(URL, headers=_h(emissor, "elaboracao-0002"))
    assert primeiro.status_code == 202 and segundo.status_code == 200
    assert primeiro.json()["id"] == segundo.json()["id"]
    assert len(banco.jobs) == 1 and len(fila.avisos) == 1


def test_corrida_entre_abas_cai_no_indice_e_devolve_o_job(api, emissor, banco, fila, monkeypatch):
    # Duas requisições passaram juntas da leitura: quem decide é o índice.
    leituras = iter([None])
    original = el._job_recente
    monkeypatch.setattr(el, "_job_recente", lambda *a, **k: next(leituras, "fim") and original(*a, **k))
    banco.jobs.append({"id": str(uuid.uuid4()), "tipo": el.TIPO_JOB, "recurso_id": PROCESSO, "estado": "running",
                       "auth_user_id": USUARIO_A, "feitos": 1, "total": 5, "erro_codigo": "", "resultado": {},
                       "criado_em": _agora(), "atualizado_em": _agora(), "iniciado_em": None, "concluido_em": None})
    r = api.post(URL, headers=_h(emissor))
    assert r.status_code == 200 and r.json()["id"] == banco.jobs[0]["id"]
    assert len(banco.jobs) == 1 and not fila.avisos


def test_job_abandonado_nao_trava_para_sempre(api, emissor, banco, fila):
    velho = (datetime.now(timezone.utc) - timedelta(seconds=el.ABANDONADO_S + 60)).isoformat()
    banco.jobs.append({"id": str(uuid.uuid4()), "tipo": el.TIPO_JOB, "recurso_id": PROCESSO, "estado": "running",
                       "auth_user_id": USUARIO_A, "feitos": 2, "total": 5, "erro_codigo": "",
                       "resultado": {"documento": "dfd"}, "criado_em": velho, "atualizado_em": velho,
                       "iniciado_em": velho, "concluido_em": None})
    corpo = api.get(URL, headers=_h(emissor)).json()
    assert corpo["job"]["estado"] == "failed" and corpo["job"]["erro_codigo"] == "ABANDONED"
    assert api.post(URL, headers=_h(emissor)).status_code == 202
    assert len(banco.jobs) == 2


def test_quem_nao_e_titular_nem_admin_nao_elabora(api, emissor, banco):
    banco.processo["auth_user_id"] = OUTRO_USUARIO
    assert api.post(URL, headers=_h(emissor)).status_code == 403
    assert not banco.jobs


def test_documento_que_nao_e_o_proximo_e_conflito(api, emissor, banco):
    assert api.post(URL, headers=_h(emissor), json={"tipo": "etp"}).status_code == 409
    banco.processo["documentos"] = {"dfd": "gerado"}
    assert api.post(URL, headers=_h(emissor)).status_code == 409
    assert not banco.jobs


def test_fila_fora_do_ar_nao_deixa_job_preso(emissor, banco, flags):
    api = _montar(emissor, banco, FilaFalsa(quebrar=True))
    r = api.post(URL, headers=_h(emissor))
    assert r.status_code == 503 and r.json()["code"] == "QUEUE_UNAVAILABLE"
    assert banco.jobs[0]["estado"] == "failed" and banco.jobs[0]["erro_codigo"] == "QUEUE_UNAVAILABLE"


def test_contexto_vem_da_revisao_aprovada_no_editor(api, emissor, banco):
    banco.processo["documentos"] = {"dfd": "texto gerado, sem as edições"}
    banco.cabecas = [{"id": dn.id_do_documento(PROCESSO, "dfd"), "tipo": "dfd", "revision": 4, "status": "aprovado"}]
    r = api.post(URL, headers=_h(emissor))
    assert r.status_code == 202, r.text
    contexto = banco.jobs[0]["parametros"]["contexto"]
    assert "Texto aprovado do DFD no editor." in contexto and "sem as edições" not in contexto
    assert banco.jobs[0]["parametros"]["tipo"] == "etp"


def test_lista_e_detalhe_contam_a_aprovacao_do_editor(api, emissor, banco):
    banco.processo["documentos"] = {"dfd": "texto"}
    banco.responder("GET", "documentos_editor", 200, [{"processo_id": PROCESSO, "tipo": "dfd"}])
    corpo = api.get(f"/api/v1/processos/{PROCESSO}", headers=_h(emissor)).json()
    assert corpo["progresso"]["feitos"] == 1
    # A linha gravada não muda: o dono documental não toca em `aprovados`.
    assert banco.processo["aprovados"] == []


def test_sem_leitura_das_cabecas_o_progresso_fica_como_estava(api, emissor, banco):
    banco.processo["aprovados"] = ["dfd"]
    banco.processo["documentos"] = {"dfd": "texto"}
    banco.responder("GET", "documentos_editor", 500, {"code": "XX000"})
    corpo = api.get(f"/api/v1/processos/{PROCESSO}", headers=_h(emissor)).json()
    assert corpo["progresso"]["feitos"] == 1


def test_sessao_recusada_na_leitura_das_cabecas_continua_401(api, emissor, banco):
    # Tolerar a indisponibilidade não pode esconder token vencido.
    banco.responder("GET", "documentos_editor", 401, {"code": "PGRST301"})
    assert api.get(f"/api/v1/processos/{PROCESSO}", headers=_h(emissor)).status_code == 401


# ---------------------------------------------------------------------------
# Worker
# ---------------------------------------------------------------------------
def test_gera_de_verdade_e_entrega_para_revisao(api, emissor, banco, fila, motor):
    assert api.post(URL, headers=_h(emissor)).status_code == 202
    job = banco.jobs[0]
    assert _rodar(banco, job["id"], emissor) == "succeeded"
    assert len(motor) == 1 and "Papel A4 sintético" in motor[0]
    texto = banco.processo["documentos"]["dfd"]
    assert "redigida pelo motor" in texto and "[[TABELA_ITENS]]" not in texto and "Papel A4" in texto
    assert job["estado"] == "succeeded" and job["feitos"] == job["total"]
    corpo = api.get(URL, headers=_h(emissor)).json()
    assert corpo["proximo"] == {"acao": "revisar", "tipo": "dfd", "sigla": "DFD"}
    assert corpo["documentos"][0]["situacao"] == "gerado" and corpo["job"] is None
    # Gerar não aprova.
    assert banco.processo["aprovados"] == []


def test_campo_a_preencher_aparece_antes_da_aprovacao(api, emissor, banco, motor, monkeypatch):
    # O que `DocumentoService.aprovar` recusaria sem dizer qual foi.
    def com_marcador(*a, **k):
        return TEXTO_DA_IA + "\n1.2. Responsável: [PREENCHER: matrícula do responsável].\n"

    monkeypatch.setattr(llm, "_chamar_motor", com_marcador)
    api.post(URL, headers=_h(emissor))
    _rodar(banco, banco.jobs[0]["id"], emissor)
    corpo = api.get(URL, headers=_h(emissor)).json()
    assert corpo["bloqueios"] >= 1
    assert any("matrícula do responsável" in p for p in corpo["pendencias"])

    # Revisão salva: o texto já é outro, e a lista antiga mentiria.
    banco.cabecas = [{"id": dn.id_do_documento(PROCESSO, "dfd"), "tipo": "dfd", "revision": 2, "status": "rascunho"}]
    corpo = api.get(URL, headers=_h(emissor)).json()
    assert corpo["bloqueios"] == 0 and corpo["pendencias"] == []


def test_job_antigo_sem_lista_ainda_informa_a_contagem(api, emissor, banco):
    banco.processo["documentos"] = {"dfd": "texto"}
    banco.jobs.append({"id": str(uuid.uuid4()), "tipo": el.TIPO_JOB, "recurso_id": PROCESSO, "estado": "succeeded",
                       "auth_user_id": USUARIO_A, "feitos": 5, "total": 5, "erro_codigo": "",
                       "resultado": {"documento": "dfd", "bloqueios": 3, "avisos": 0},
                       "criado_em": _agora(), "atualizado_em": _agora(), "iniciado_em": None, "concluido_em": None})
    corpo = api.get(URL, headers=_h(emissor)).json()
    assert corpo["bloqueios"] == 3 and corpo["pendencias"] == []


def test_edital_sai_do_catalogo_sem_ia_e_leva_a_ata(api, emissor, banco, motor):
    banco.processo["dados"] = {**_completos(), "modelo_execucao": "Sistema de Registro de Preços"}
    banco.processo["documentos"] = {"dfd": "a", "etp": "b", "tr": "c"}
    banco.processo["aprovados"] = ["dfd", "etp", "tr"]
    assert api.post(URL, headers=_h(emissor), json={"tipo": "edital"}).status_code == 202
    assert _rodar(banco, banco.jobs[0]["id"], emissor) == "succeeded"
    assert motor == []
    assert banco.processo["documentos"]["edital"] and banco.processo["documentos"]["arp"]
    assert banco.processo["etapa"] == 4


def test_progresso_e_real_e_em_ordem(api, emissor, banco, motor, monkeypatch):
    assert api.post(URL, headers=_h(emissor)).status_code == 202
    vistos = []
    original = el.atualizar_job
    monkeypatch.setattr(el, "atualizar_job", lambda rest, token, jid, **c: (
        vistos.append(c["feitos"]) if "feitos" in c else None, original(rest, token, jid, **c))[1])
    _rodar(banco, banco.jobs[0]["id"], emissor)
    assert vistos == [0, 1, 2, 3, 4, 5]


def test_mapa_do_fluxo_fica_gravado_no_processo(api, emissor, banco, flags, motor):
    flags.add("mapa_riscos")
    api.post(URL, headers=_h(emissor))
    _rodar(banco, banco.jobs[0]["id"], emissor)
    assert banco.processo["dados"][CHAVE_FLUXO_MAPA] is True


def test_motor_fora_do_ar_falha_com_mensagem_e_preserva_o_processo(api, emissor, banco, motor, monkeypatch):
    def caiu(*a, **k):
        raise llm.ErroGeracaoIA("O serviço de IA não respondeu. Tente de novo.")

    monkeypatch.setattr(llm, "_chamar_motor", caiu)
    api.post(URL, headers=_h(emissor))
    assert _rodar(banco, banco.jobs[0]["id"], emissor) == "failed"
    assert banco.processo["documentos"] == {}
    corpo = api.get(URL, headers=_h(emissor)).json()
    assert corpo["job"]["erro_codigo"] == "AI_UNAVAILABLE"
    assert corpo["job"]["resultado"]["mensagem"].startswith("O serviço de IA")
    # Tentar de novo é pedir outro job: a falha não trava o processo.
    assert api.post(URL, headers=_h(emissor, "elaboracao-0002")).status_code == 202


def test_erro_inesperado_nao_vaza_detalhe(api, emissor, banco, motor, monkeypatch):
    def quebrou(*a, **k):
        raise ValueError("trecho sigiloso do processo")

    monkeypatch.setattr(llm, "_chamar_motor", quebrou)
    api.post(URL, headers=_h(emissor))
    assert _rodar(banco, banco.jobs[0]["id"], emissor) == "failed"
    assert banco.jobs[0]["erro_codigo"] == "GENERATION_FAILED"
    assert "sigiloso" not in json.dumps(banco.jobs[0]["resultado"])


def test_processo_alterado_durante_a_geracao_nao_e_sobrescrito(api, emissor, banco, motor, monkeypatch):
    def editou_no_meio(*a, **k):
        banco.processo["dados"] = {**banco.processo["dados"], "objeto": "Mudou no meio"}
        return TEXTO_DA_IA

    monkeypatch.setattr(llm, "_chamar_motor", editou_no_meio)
    api.post(URL, headers=_h(emissor))
    assert _rodar(banco, banco.jobs[0]["id"], emissor) == "failed"
    assert banco.jobs[0]["erro_codigo"] == "CONTEXT_CHANGED"
    assert banco.processo["documentos"] == {}


def test_cas_perdido_na_gravacao_nao_sobrescreve(api, emissor, banco, motor, monkeypatch):
    api.post(URL, headers=_h(emissor))
    banco.responder("PATCH", "processos", 200, [])
    assert _rodar(banco, banco.jobs[0]["id"], emissor) == "failed"
    assert banco.jobs[0]["erro_codigo"] == "CONTEXT_CHANGED"
    assert banco.processo["documentos"] == {}


def test_aviso_repetido_nao_gera_de_novo(api, emissor, banco, motor):
    api.post(URL, headers=_h(emissor))
    job = banco.jobs[0]
    _rodar(banco, job["id"], emissor)
    assert _rodar(banco, job["id"], emissor) == "succeeded"
    assert len(motor) == 1


def test_queda_depois_de_gravar_nao_gasta_outra_chamada(api, emissor, banco, motor):
    api.post(URL, headers=_h(emissor))
    job = banco.jobs[0]
    banco.processo["documentos"] = {"dfd": "gravado pela entrega anterior"}
    assert _rodar(banco, job["id"], emissor) == "succeeded"
    assert motor == [] and job["estado"] == "succeeded"


def test_token_no_fim_nao_comeca(api, emissor, banco, motor, monkeypatch):
    api.post(URL, headers=_h(emissor))
    monkeypatch.setattr(el, "expiracao_do_token", lambda _t: time.time() + coleta.MARGEM_DO_TOKEN_S - 1)
    assert _rodar(banco, banco.jobs[0]["id"], emissor) == "failed"
    assert banco.jobs[0]["erro_codigo"] == "SESSION_EXPIRED" and motor == []


def test_resultado_expoe_so_o_que_a_tela_usa():
    saida = coleta._resultado_exibivel({"documento": "dfd", "bloqueios": 1, "avisos": 2, "contexto": "x",
                                        "pendencias": ["campo", 7]})
    assert saida == {"documento": "dfd", "bloqueios": 1, "avisos": 2, "pendencias": ["campo"]}


def test_lista_de_pendencias_cabe_no_limite_do_job():
    achados = [{"pendencia": {"campo": "x" * 500}} for _ in range(dominio.MAX_PENDENCIAS)]
    lista = [dominio._pendencia(a) for a in achados]
    assert len(json.dumps(lista, ensure_ascii=False).encode()) < 3500


def test_a_fila_leva_o_usuario_e_esconde_o_token():
    from govconect_api.fila import FilaCelery

    enviados = []

    class App:
        def send_task(self, nome, **kw):
            enviados.append((nome, kw))

    FilaCelery(App()).enfileirar(job_id="j", token="t.o.k", tenant_id="a", auth_user_id="b",
                                 secretaria_id=None, usuario_id="u", tarefa="elaboracao")
    nome, kw = enviados[0]
    assert nome == "govconect.elaborar_documento" and kw["args"][-1] == "u"
    assert "t.o.k" not in kw["argsrepr"]
