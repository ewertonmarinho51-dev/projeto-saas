"""
WordCraft Workspace na API (Issue #137) contra um dono documental SIMULADO.

A ponte é a real (`src.wordcraft_protocol.Ponte`) e os eventos têm o formato
exato que `assets/wordcraft_editor/host.mjs` publica. O dono documental é
falso, mas com CAS de verdade: revisão esperada diferente da cabeça é
conflito, e repetir a mesma operação devolve o mesmo recibo. O que estas
provas fecham é o que este módulo decide — trava de ativação, dono da
sessão, ACK só depois do commit, conflito que não sobrescreve, aprovação só
com canvas bloqueado e a janela estreita da credencial documental.
"""

from __future__ import annotations

import base64
import hashlib
import os
import uuid
from types import SimpleNamespace

import httpx
import pytest
from fastapi.testclient import TestClient

from govconect_api import documentos_nativos as dn
from govconect_api.config import ConfiguracaoInvalida, carregar
from govconect_api.escrita_documental import ClienteDocumental, RPCS
from govconect_api.main import criar_app
from govconect_api.verificador import VerificadorSupabase
from src import db
from src.documentos_editor import AcessoNegado, ConflitoDocumento, ErroDocumento

from apoio_jwt import EMISSOR, TENANT_A, Emissor, PostgrestFalso

PROCESSO = "cccccccc-0000-4000-8000-0000000000d1"
DFD = dn.id_do_documento(PROCESSO, "dfd")
ETP = dn.id_do_documento(PROCESSO, "etp")
ORIGEM = "https://govconect.com"
OUTRO_USUARIO = "bbbbbbbb-0000-4000-8000-00000000b001"


def _sha(dados: bytes) -> str:
    return hashlib.sha256(dados).hexdigest()


# ---------------------------------------------------------------------------
# Dublês
# ---------------------------------------------------------------------------
class _Resultado:
    def __init__(self, dados=None):
        self.dados = dados

    def execute(self):
        return SimpleNamespace(data=self.dados)


class ClienteGravador:
    def __init__(self, nome):
        self.nome, self.rpcs, self.tabelas = nome, [], []

    def rpc(self, nome, parametros=None, *a, **k):
        self.rpcs.append(nome)
        return _Resultado({"ok": True})

    def table(self, nome):
        self.tabelas.append(nome)
        return _Resultado([])


class ServicoFalso:
    """Mesma interface que a API usa do `DocumentoService`."""

    def __init__(self):
        self.revisoes: dict[str, list[bytes]] = {}
        self.status: dict[str, str] = {}
        self.recibos: dict[str, SimpleNamespace] = {}
        self.aprovacoes: list = []
        self.importados: list = []

    def semear(self, tipo="dfd", conteudo=b"revisao-1"):
        did = dn.id_do_documento(PROCESSO, tipo)
        self.revisoes[did] = [conteudo]
        self.status[did] = "rascunho"
        return did

    def _doc(self, did, revisao=None):
        revs = self.revisoes[did]
        n = revisao or len(revs)
        tipo = dn.tipo_do_documento(PROCESSO, did)
        return SimpleNamespace(id=did, processo_id=PROCESSO, tipo=tipo, revision=n,
                               content_hash=_sha(revs[n - 1]), status=self.status[did], payload=revs[n - 1])

    def abrir(self, did):
        if did not in self.revisoes:
            raise AcessoNegado("Documento não disponível nesta sessão.")
        return self._doc(did)

    def importar_legado(self, *, processo_id, tipo, operation_id, formato):
        assert isinstance(db._cliente(), ClienteDocumental), "importação fora da janela documental"
        db._cliente().rpc("documento_editor_checkpoint", {}).execute()
        self.importados.append(operation_id)
        return self.abrir(self.semear(tipo, b"importado-" + tipo.encode()))

    def checkpoint(self, did, ck):
        cliente = db._cliente()
        assert isinstance(cliente, ClienteDocumental), "commit fora da janela documental"
        if ck.request_id in self.recibos:
            return self.recibos[ck.request_id]
        if ck.expected_revision != len(self.revisoes[did]):
            raise ConflitoDocumento("A revisão ou operação documental divergiu.")
        cliente.table("documentos_editor").execute()
        cliente.rpc("documento_editor_checkpoint", {}).execute()
        self.revisoes[did].append(ck.content)
        recibo = SimpleNamespace(request_id=ck.request_id, revision=len(self.revisoes[did]),
                                 content_hash=ck.content_hash)
        self.recibos[ck.request_id] = recibo
        return recibo

    def historico_revisoes(self, did):
        atual = len(self.revisoes[did])
        return {"revisions": [{"revision": n, "contentHash": _sha(self.revisoes[did][n - 1]),
                               "current": n == atual, "indexMode": "reconciled",
                               "status": self.status[did] if n == atual else "historico"}
                              for n in range(atual, 0, -1)]}

    def restaurar(self, did, *, source_revision, expected_revision, operation_id):
        assert isinstance(db._cliente(), ClienteDocumental)
        if expected_revision != len(self.revisoes[did]):
            raise ConflitoDocumento("A revisão ou operação documental divergiu.")
        conteudo = self.revisoes[did][source_revision - 1]
        self.revisoes[did].append(conteudo)
        return SimpleNamespace(revision=len(self.revisoes[did]), content_hash=_sha(conteudo))

    def aprovar(self, vinculo):
        assert isinstance(db._cliente(), ClienteDocumental)
        db._cliente().rpc("documento_editor_aprovar", {}).execute()
        cabeca = self._doc(vinculo.document_id)
        if (cabeca.revision, cabeca.content_hash) != (vinculo.revision, vinculo.content_hash):
            raise ConflitoDocumento("A revisão mudou; reabra o documento antes de aprovar.")
        self.aprovacoes.append(vinculo)
        self.status[vinculo.document_id] = "aprovado"
        return SimpleNamespace(id=str(uuid.uuid4()), document_id=vinculo.document_id,
                               revision=vinculo.revision, content_hash=vinculo.content_hash,
                               status="aprovado", replayed=False)

    def exportar(self, did, *, expected_revision, content_hash, formato):
        cabeca = self._doc(did)
        if (cabeca.revision, cabeca.content_hash) != (expected_revision, content_hash):
            raise ConflitoDocumento("A revisão persistida mudou antes da exportação.")
        payload = (b"%PDF-" if formato == "pdf" else b"PK\x03\x04") + cabeca.payload
        return SimpleNamespace(revision=cabeca.revision, content_hash=_sha(payload), payload=payload)


# ---------------------------------------------------------------------------
# Montagem
# ---------------------------------------------------------------------------
# Montada na hora: a varredura de segredos do CI olha o texto do arquivo.
CHAVE = "sb_secret_" + "d" * 24
AMBIENTE = {"APP_ENV": "test", "SUPABASE_URL": "https://exemplo-staging.supabase.co",
            "SUPABASE_KEY": "chave-publicavel-de-teste", "GOVCONECT_WORDCRAFT_WORKSPACE": "on",
            "GOVCONECT_DOCUMENTOS_ESCRITA_KEY": CHAVE}


@pytest.fixture
def emissor():
    return Emissor()


class BancoComProcesso(PostgrestFalso):
    """O processo do teste existe e é visível, salvo resposta enfileirada."""

    def __call__(self, request):
        if request.url.path.endswith("/processos") and not self.respostas.get(("GET", "processos")):
            self.chamadas.append(request)
            return httpx.Response(200, json=[{"id": PROCESSO, "documentos": {}}])
        return super().__call__(request)


@pytest.fixture
def banco():
    return BancoComProcesso()


@pytest.fixture
def canario(monkeypatch):
    estado = {"ligado": True}
    monkeypatch.setattr(dn.contexto, "modulo_em_rollout_aqui",
                        lambda modulo: modulo == dn.FLAG_CANARIO and estado["ligado"])
    return estado


@pytest.fixture
def servico():
    return ServicoFalso()


@pytest.fixture
def clientes(monkeypatch):
    usuario, servidor = ClienteGravador("usuario"), ClienteGravador("servidor")
    monkeypatch.setattr(db, "cliente_do_usuario", lambda: usuario)
    return SimpleNamespace(usuario=usuario, servidor=servidor)


def _montar(emissor, banco, servico, clientes, ambiente=AMBIENTE):
    rest = banco.cliente()
    app = criar_app(carregar(ambiente),
                    verificador=VerificadorSupabase(emissor=EMISSOR, rest=rest, chave_para=emissor.chave_para),
                    rest=rest)
    app.state.motor_documental = dn.Motor(servico, ORIGEM, ORIGEM + "/app/static/wordcraft/gc.js",
                                          ORIGEM + "/app/static/wordcraft/gc_bg.wasm")
    app.state.fabrica_documental = lambda url, chave: clientes.servidor
    return TestClient(app, raise_server_exceptions=False)


@pytest.fixture
def api(emissor, banco, servico, clientes, canario):
    return _montar(emissor, banco, servico, clientes)


def _auth(emissor, **kw):
    return {"Authorization": f"Bearer {emissor.token(**kw)}"}


def _abrir(api, emissor, did=DFD, **kw):
    r = api.post(f"/api/v1/documentos/{did}/sessoes", headers=_auth(emissor, **kw),
                 json={"processo_id": PROCESSO})
    assert r.status_code == 200, r.text
    return r.json()


class Host:
    """Os eventos que o host.mjs publica, na mesma ordem e forma."""

    def __init__(self, abertura):
        self.a = abertura
        self.seq = abertura["event_ack"]
        self.revisao = abertura["revision"]
        self.eventos = []

    def _evento(self, tipo, payload, request_id=None):
        self.seq += 1
        evento = {"protocol": "gc-wordcraft/v1", "request_id": request_id or str(uuid.uuid4()),
                  "instance_id": self.a["instance_id"], "session_id": self.a["session_id"],
                  "document_id": self.a["document_id"], "expected_revision": self.revisao,
                  "event": tipo, "sequence": self.seq, "nonce": self.a["nonce"], "payload": payload}
        self.eventos.append(evento)
        return evento

    def carregado(self):
        return self._evento("document.loaded", {"content_hash": self.a["content_hash"]})

    def mudou(self):
        return self._evento("document.changed", {})

    def checkpoint(self, conteudo: bytes):
        return self._evento("document.checkpoint", {
            "schema_version": "gc-wordcraft-snapshot/v1", "content_hash": _sha(conteudo),
            "content_base64": base64.b64encode(conteudo).decode()})

    def congelado(self, controle):
        return self._evento("document.frozen", {"command_id": controle["command_id"],
                                                "content_hash": controle["content_hash"],
                                                "generation": "7"})

    def enviar(self, api, emissor, **kw):
        r = api.post(f"/api/v1/documentos/{self.a['document_id']}/sessoes/{self.a['instance_id']}/eventos",
                     headers=_auth(emissor, **kw), json={"events": self.eventos})
        if r.status_code == 200:
            # O outbox do host descarta o que a ponte confirmou ter consumido.
            ack = r.json()["event_ack"]
            self.eventos = [e for e in self.eventos if e["sequence"] > ack]
            if r.json()["ack"]:
                self.revisao = r.json()["revision"]
        return r


# ---------------------------------------------------------------------------
# Ativação
# ---------------------------------------------------------------------------
def test_trava_do_ambiente_desligada_e_404(emissor, banco, servico, clientes, canario):
    api = _montar(emissor, banco, servico, clientes, {**AMBIENTE, "GOVCONECT_WORDCRAFT_WORKSPACE": ""})
    servico.semear()
    for r in (api.get(f"/api/v1/processos/{PROCESSO}/documentos", headers=_auth(emissor)),
              api.post(f"/api/v1/documentos/{DFD}/sessoes", headers=_auth(emissor),
                       json={"processo_id": PROCESSO})):
        assert r.status_code == 404 and r.json()["code"] == "MODULE_UNAVAILABLE"


def test_tenant_fora_do_canario_e_404(api, emissor, servico, canario):
    servico.semear()
    canario["ligado"] = False
    r = api.post(f"/api/v1/documentos/{DFD}/sessoes", headers=_auth(emissor), json={"processo_id": PROCESSO})
    assert r.status_code == 404 and r.json()["code"] == "MODULE_UNAVAILABLE"


def test_sem_token_e_401(api):
    assert api.get(f"/api/v1/processos/{PROCESSO}/documentos").status_code == 401


# ---------------------------------------------------------------------------
# Lista e abertura
# ---------------------------------------------------------------------------
def test_lista_nativos_e_legados_com_o_id_deterministico(api, emissor, banco):
    banco.responder("GET", "processos", 200, [{"id": PROCESSO, "documentos": {"etp": "# ETP", "tr": ""}}])
    banco.responder("GET", "documentos_editor", 200, [
        {"id": DFD, "tipo": "dfd", "revision": 3, "content_hash": "a" * 64, "status": "rascunho"},
        # Cabeça fora do id determinístico não é do contrato: não aparece.
        {"id": str(uuid.uuid4()), "tipo": "mapa_riscos", "revision": 1, "status": "rascunho"}])
    r = api.get(f"/api/v1/processos/{PROCESSO}/documentos", headers=_auth(emissor))
    assert r.status_code == 200, r.text
    docs = {d["tipo"]: d for d in r.json()["documentos"]}
    assert set(docs) == {"dfd", "etp"}
    assert docs["dfd"] == {"id": DFD, "tipo": "dfd", "sigla": "DFD", "rotulo": dn.TIPOS["dfd"],
                           "nativo": True, "legado": False, "revisao": 3, "content_hash": "a" * 64,
                           "status": "rascunho"}
    assert docs["etp"]["nativo"] is False and docs["etp"]["legado"] is True and docs["etp"]["id"] == ETP
    assert r.json()["escrita"] is True


def test_processo_de_outro_municipio_e_404(api, emissor, banco):
    banco.responder("GET", "processos", 200, [])
    r = api.get(f"/api/v1/processos/{PROCESSO}/documentos", headers=_auth(emissor))
    assert r.status_code == 404
    consulta = next(c for c in banco.chamadas if c.url.path.endswith("/processos"))
    assert f"eq.{TENANT_A}" in str(consulta.url), "o tenant vem do token, nunca do pedido"


def test_documento_que_nao_e_do_processo_e_404(api, emissor, servico):
    servico.semear()
    r = api.post(f"/api/v1/documentos/{uuid.uuid4()}/sessoes", headers=_auth(emissor),
                 json={"processo_id": PROCESSO})
    assert r.status_code == 404


def test_abertura_entrega_a_revisao_persistida_e_a_ponte_nova(api, emissor, servico):
    servico.semear(conteudo=b"conteudo-original")
    a = _abrir(api, emissor)
    assert a["document_id"] == DFD and a["tipo"] == "dfd" and a["sigla"] == "DFD"
    assert a["revision"] == 1 and a["content_hash"] == _sha(b"conteudo-original")
    assert base64.b64decode(a["checkpoint_base64"]) == b"conteudo-original"
    assert a["estado"] == "opening" and a["event_ack"] == 0 and a["ack"] is None
    assert 32 <= len(a["nonce"]) <= 128
    assert a["module_url"].startswith(ORIGEM + "/app/static/wordcraft/")
    b = _abrir(api, emissor)
    assert b["instance_id"] != a["instance_id"] and b["nonce"] != a["nonce"]


def test_sem_cabeca_nativa_importa_o_legado_so_com_credencial(emissor, banco, servico, clientes, canario):
    sem = _montar(emissor, banco, servico, clientes, {**AMBIENTE, "GOVCONECT_DOCUMENTOS_ESCRITA_KEY": ""})
    r = sem.post(f"/api/v1/documentos/{ETP}/sessoes", headers=_auth(emissor), json={"processo_id": PROCESSO})
    assert r.status_code == 503 and r.json()["code"] == "DOCUMENT_WRITE_UNAVAILABLE"
    assert servico.importados == [] and clientes.servidor.rpcs == []

    com = _montar(emissor, banco, servico, clientes)
    r = com.post(f"/api/v1/documentos/{ETP}/sessoes", headers=_auth(emissor), json={"processo_id": PROCESSO})
    assert r.status_code == 200, r.text
    assert servico.importados == [str(uuid.uuid5(uuid.NAMESPACE_URL,
                                                 f"govconnect-wordcraft-import:{PROCESSO}:etp"))]
    assert clientes.servidor.rpcs == ["documento_editor_checkpoint"]


def test_motor_indisponivel_e_503_sem_vazar_detalhe(emissor, banco, servico, clientes, canario, monkeypatch):
    api = _montar(emissor, banco, servico, clientes)
    api.app.state.motor_documental = None
    monkeypatch.setattr(dn, "carregar_motor", lambda: (_ for _ in ()).throw(RuntimeError("/opt/segredo")))
    r = api.post(f"/api/v1/documentos/{DFD}/sessoes", headers=_auth(emissor), json={"processo_id": PROCESSO})
    assert r.status_code == 503 and r.json()["code"] == "WORDCRAFT_RUNTIME_UNAVAILABLE"
    assert "segredo" not in r.text


# ---------------------------------------------------------------------------
# Salvar: ACK só depois do commit; conflito nunca sobrescreve
# ---------------------------------------------------------------------------
def test_checkpoint_commita_e_so_entao_confirma(api, emissor, servico, clientes):
    servico.semear()
    a = _abrir(api, emissor)
    host = Host(a)
    host.carregado()
    host.mudou()
    pedido = host.checkpoint(b"revisao-2")["request_id"]
    r = host.enviar(api, emissor)
    assert r.status_code == 200, r.text
    e = r.json()
    assert e["event_ack"] == 3 and e["estado"] == "saved"
    assert e["ack"] == {"request_id": pedido, "revision": 2, "content_hash": _sha(b"revisao-2")}
    assert servico.revisoes[DFD] == [b"revisao-1", b"revisao-2"]
    # A credencial documental levou SÓ a RPC de commit; a leitura foi com o JWT.
    assert clientes.servidor.rpcs == ["documento_editor_checkpoint"] and clientes.servidor.tabelas == []
    assert clientes.usuario.tabelas == ["documentos_editor"]
    assert db.CLIENTE_DOCUMENTAL.get() is None, "a janela fecha ao fim da requisição"


def test_lote_repetido_nao_grava_duas_vezes(api, emissor, servico):
    servico.semear()
    host = Host(_abrir(api, emissor))
    host.carregado()
    host.mudou()
    host.checkpoint(b"revisao-2")
    lote = list(host.eventos)
    assert host.enviar(api, emissor).json()["ack"]["revision"] == 2
    # O outbox reenvia o prefixo já consumido (rerun, rede): a ponte ignora.
    host.eventos = lote
    r = host.enviar(api, emissor)
    assert r.status_code == 200 and r.json()["ack"]["revision"] == 2
    assert len(servico.revisoes[DFD]) == 2


def test_sem_credencial_o_checkpoint_fica_pendente_para_retry(emissor, banco, servico, clientes, canario):
    api = _montar(emissor, banco, servico, clientes, {**AMBIENTE, "GOVCONECT_DOCUMENTOS_ESCRITA_KEY": ""})
    servico.semear()
    host = Host(_abrir(api, emissor))
    assert host.carregado() and host.mudou() and host.checkpoint(b"revisao-2")
    e = host.enviar(api, emissor).json()
    assert e["estado"] == "error" and e["ack"] is None and e["escrita"] is False
    assert e["save_error"]["conflict"] is False
    assert servico.revisoes[DFD] == [b"revisao-1"] and clientes.servidor.rpcs == []


def test_duas_sessoes_concorrentes_a_segunda_vira_conflito(api, emissor, servico):
    servico.semear()
    primeira, segunda = Host(_abrir(api, emissor)), Host(_abrir(api, emissor))
    for h in (primeira, segunda):
        h.carregado()
        h.mudou()
    primeira.checkpoint(b"da-primeira")
    assert primeira.enviar(api, emissor).json()["ack"]["revision"] == 2
    segunda.checkpoint(b"da-segunda")
    e = segunda.enviar(api, emissor).json()
    assert e["estado"] == "conflict" and e["save_error"] == {"request_id": e["save_error"]["request_id"],
                                                             "conflict": True}
    assert e["ack"] is None
    assert servico.revisoes[DFD] == [b"revisao-1", b"da-primeira"], "conflito jamais sobrescreve"


def test_lote_adulterado_e_recusado_pela_ponte(api, emissor, servico):
    servico.semear()
    host = Host(_abrir(api, emissor))
    host.carregado()["nonce"] = "x" * 64
    r = host.enviar(api, emissor)
    assert r.status_code == 409 and r.json()["code"] == "EDITOR_PROTOCOL_REJECTED"


def test_sessao_de_outra_conta_ou_outro_municipio_nao_existe(api, emissor, servico):
    servico.semear()
    host = Host(_abrir(api, emissor))
    host.carregado()
    for kw in ({"sub": OUTRO_USUARIO}, {"tenant": "bbbbbbbb-0000-4000-8000-000000000002"}):
        r = host.enviar(api, emissor, **kw)
        assert r.status_code in (403, 404), r.text
        if r.status_code == 404:
            assert r.json()["code"] == "EDITOR_SESSION_NOT_FOUND"
    assert host.enviar(api, emissor).status_code == 200, "o dono continua com a sessão"


def test_sessao_de_outro_documento_nao_serve(api, emissor, servico):
    servico.semear()
    servico.semear("etp")
    a = _abrir(api, emissor)
    r = api.get(f"/api/v1/documentos/{ETP}/sessoes/{a['instance_id']}", headers=_auth(emissor))
    assert r.status_code == 404


# ---------------------------------------------------------------------------
# Revisão: bloqueio → aprovação
# ---------------------------------------------------------------------------
def test_aprovar_exige_canvas_bloqueado_na_revisao_salva(api, emissor, servico, clientes):
    servico.semear()
    a = _abrir(api, emissor)
    host = Host(a)
    host.carregado()
    host.mudou()
    caminho = f"/api/v1/documentos/{DFD}/sessoes/{a['instance_id']}"
    # Edição suja: nem bloqueio nem aprovação.
    assert host.enviar(api, emissor).json()["estado"] == "dirty"
    assert api.post(caminho + "/bloqueio", headers=_auth(emissor)).status_code == 409
    assert api.post(caminho + "/aprovacao", headers=_auth(emissor)).json()["code"] == "EDITOR_NOT_FROZEN"
    host.checkpoint(b"revisao-2")
    assert host.enviar(api, emissor).json()["estado"] == "saved"

    controle = api.post(caminho + "/bloqueio", headers=_auth(emissor)).json()["control"]
    assert controle["action"] == "freeze" and controle["revision"] == 2
    host.congelado(controle)
    assert host.enviar(api, emissor).json()["bloqueado"] is True

    r = api.post(caminho + "/aprovacao", headers=_auth(emissor))
    assert r.status_code == 200, r.text
    vinculo = servico.aprovacoes[0]
    assert (vinculo.document_id, vinculo.revision, vinculo.content_hash) == (DFD, 2, _sha(b"revisao-2"))
    assert r.json()["status"] == "aprovado"
    assert "documento_editor_aprovar" in clientes.servidor.rpcs


def test_recusa_do_dono_na_aprovacao_vira_422_com_a_mensagem_dele(api, emissor, servico, monkeypatch):
    servico.semear()
    a = _abrir(api, emissor)
    host = Host(a)
    host.carregado()
    caminho = f"/api/v1/documentos/{DFD}/sessoes/{a['instance_id']}"
    host.enviar(api, emissor)
    host.congelado(api.post(caminho + "/bloqueio", headers=_auth(emissor)).json()["control"])
    host.enviar(api, emissor)
    monkeypatch.setattr(servico, "aprovar", lambda v: (_ for _ in ()).throw(
        ErroDocumento("Confirme os fatos canônicos antes de aprovar.")))
    r = api.post(caminho + "/aprovacao", headers=_auth(emissor))
    assert r.status_code == 422 and "fatos canônicos" in r.json()["message"]


# ---------------------------------------------------------------------------
# Histórico, restauração e exportação
# ---------------------------------------------------------------------------
def test_restaurar_cria_revisao_nova_e_reabre_o_canvas(api, emissor, servico):
    servico.semear()
    a = _abrir(api, emissor)
    host = Host(a)
    host.carregado()
    host.mudou()
    host.checkpoint(b"revisao-2")
    host.enviar(api, emissor)
    hist = api.get(f"/api/v1/documentos/{DFD}/historico", params={"processo_id": PROCESSO},
                   headers=_auth(emissor)).json()
    assert [(r["revisao"], r["atual"], r["restauravel"]) for r in hist["revisoes"]] == [(2, True, False),
                                                                                      (1, False, True)]
    r = api.post(f"/api/v1/documentos/{DFD}/restauracao", headers=_auth(emissor),
                 json={"instance_id": a["instance_id"], "revisao_origem": 1})
    assert r.status_code == 200, r.text
    nova = r.json()
    assert nova["revision"] == 3 and base64.b64decode(nova["checkpoint_base64"]) == b"revisao-1"
    assert nova["instance_id"] != a["instance_id"]
    velha = api.get(f"/api/v1/documentos/{DFD}/sessoes/{a['instance_id']}", headers=_auth(emissor))
    assert velha.status_code == 404


def test_exportar_entrega_a_revisao_exata_sem_cache(api, emissor, servico):
    servico.semear()
    params = {"processo_id": PROCESSO, "formato": "pdf", "revisao": 1, "content_hash": _sha(b"revisao-1")}
    r = api.get(f"/api/v1/documentos/{DFD}/exportacao", params=params, headers=_auth(emissor))
    assert r.status_code == 200 and r.content.startswith(b"%PDF-")
    assert r.headers["content-type"] == "application/pdf"
    assert "no-store" in r.headers["cache-control"]
    assert r.headers["content-disposition"] == 'attachment; filename="dfd-revisao-1.pdf"'
    r = api.get(f"/api/v1/documentos/{DFD}/exportacao", params={**params, "revisao": 2}, headers=_auth(emissor))
    assert r.status_code == 409 and r.json()["code"] == "DOCUMENT_CONFLICT"


# ---------------------------------------------------------------------------
# Credencial documental (ADR-011)
# ---------------------------------------------------------------------------
def test_cliente_documental_so_leva_as_rpcs_de_commit_ao_servidor():
    usuario, servidor = ClienteGravador("usuario"), ClienteGravador("servidor")
    c = ClienteDocumental(usuario, servidor)
    for nome in sorted(RPCS):
        c.rpc(nome, {})
    c.rpc("documento_editor_contexto", {})
    c.rpc("documento_editor_patch_lote", {})
    c.table("processos")
    assert servidor.rpcs == sorted(RPCS) and servidor.tabelas == []
    assert usuario.rpcs == ["documento_editor_contexto", "documento_editor_patch_lote"]
    assert usuario.tabelas == ["processos"]
    with pytest.raises(AttributeError):
        c.storage  # noqa: B018
    assert RPCS == {"documento_editor_checkpoint", "documento_editor_aprovar",
                    "documento_editor_fontes_aprovacao"}


@pytest.mark.parametrize("ambiente,chave", [
    ("production", "chave-qualquer"),
    ("production", "eyJhbGciOiJIUzI1NiJ9.eyJyb2xlIjoic2VydmljZV9yb2xlIn0.x"),
    ("staging", "eyJhbGciOiJIUzI1NiJ9.eyJyb2xlIjoic2VydmljZV9yb2xlIn0.x"),
    ("development", "eyJhbGciOiJIUzI1NiJ9.eyJyb2xlIjoic2VydmljZV9yb2xlIn0.x"),
])
def test_credencial_documental_recusa_formato_errado_fora_da_pilha(ambiente, chave):
    base = {"APP_ENV": ambiente, "SUPABASE_URL": "https://x.supabase.co", "SUPABASE_KEY": "pub",
            "GOVCONECT_DOCUMENTOS_ESCRITA_KEY": chave}
    with pytest.raises(ConfiguracaoInvalida):
        carregar(base)


def test_credencial_documental_nao_repete_a_da_admin_api():
    with pytest.raises(ConfiguracaoInvalida):
        carregar({**AMBIENTE, "GOVCONECT_AUTH_ADMIN_KEY": CHAVE,
                  "GOVCONECT_DOCUMENTOS_ESCRITA_KEY": CHAVE})


def test_credencial_documental_fica_fora_do_repr():
    config = carregar(AMBIENTE)
    assert CHAVE not in repr(config)


def test_processo_fora_do_acesso_e_404_antes_do_motor(emissor, banco, servico, clientes, canario, monkeypatch):
    api = _montar(emissor, banco, servico, clientes)
    api.app.state.motor_documental = None
    monkeypatch.setattr(dn, "carregar_motor", lambda: pytest.fail("o motor não pode carregar antes do RLS"))
    banco.responder("GET", "processos", 200, [])
    r = api.post(f"/api/v1/documentos/{DFD}/sessoes", headers=_auth(emissor), json={"processo_id": PROCESSO})
    assert r.status_code == 404 and r.json()["code"] == "NOT_FOUND"


def test_worker_apaga_a_credencial_documental_ao_subir(monkeypatch):
    from govconect_api import fila

    monkeypatch.setenv("GOVCONECT_DOCUMENTOS_ESCRITA_KEY", CHAVE)
    fila.sem_credencial_de_servidor()
    assert "GOVCONECT_DOCUMENTOS_ESCRITA_KEY" not in os.environ


# ---------------------------------------------------------------------------
# Fatos canônicos: o que a aprovação exige (0037)
# ---------------------------------------------------------------------------
def _fato(status="extraido", path="objeto.descricao", fonte="formulario:objeto", **extra):
    return {"id": str(uuid.uuid4()), "path": path, "status": status, "valor": "Canetas", "fonte": fonte,
            "confianca": 0.9, "versao": 1, "tipo": "texto", **extra}


@pytest.fixture
def fatos_do_banco(monkeypatch):
    estado = {"lidos": [], "salvos": []}
    monkeypatch.setattr(dn.db, "listar_fatos", lambda pid, apenas_vigentes=True: estado["lidos"])
    monkeypatch.setattr(dn.db, "salvar_fatos", lambda fatos: estado["salvos"].extend(fatos) or fatos)
    return estado


def test_sincronizar_lista_o_que_falta_confirmar(api, emissor, banco, fatos_do_banco):
    banco.responder("GET", "processos", 200, [{"id": PROCESSO, "dados": {"objeto": "Canetas"}}])
    fatos_do_banco["lidos"] = [_fato(), _fato("confirmado", path="orgao.nome", fonte="inferencia:orgao")]
    r = api.post(f"/api/v1/processos/{PROCESSO}/fatos-canonicos/sincronizacao", headers=_auth(emissor))
    assert r.status_code == 200, r.text
    e = r.json()
    assert (e["total"], e["confirmados"], e["pronto"], e["invalidos"]) == (2, 1, False, 0)
    assert e["pendentes"][0]["campo"] == "objeto" and e["pendentes"][0]["inferido"] is False


def test_sincronizar_grava_fato_novo_e_nao_chama_rpc_sem_substituicao(api, emissor, banco, fatos_do_banco):
    banco.responder("GET", "processos", 200, [{"id": PROCESSO, "dados": {"objeto": "Canetas"}}])
    api.post(f"/api/v1/processos/{PROCESSO}/fatos-canonicos/sincronizacao", headers=_auth(emissor))
    assert "objeto.descricao" in [f["path"] for f in fatos_do_banco["salvos"]]
    assert not [c for c in banco.chamadas if "/rpc/" in c.url.path]


def test_pronto_so_com_fatos_e_todos_confirmados(api, emissor, banco, fatos_do_banco):
    caminho = f"/api/v1/processos/{PROCESSO}/fatos-canonicos/sincronizacao"
    assert api.post(caminho, headers=_auth(emissor)).json()["pronto"] is False, "sem fato não aprova"
    fatos_do_banco["lidos"] = [_fato("confirmado", path="orgao.nome")]
    assert api.post(caminho, headers=_auth(emissor)).json()["pronto"] is True
    fatos_do_banco["lidos"].append(_fato("disputado", path="valor.total"))
    e = api.post(caminho, headers=_auth(emissor)).json()
    assert e["pronto"] is False and e["invalidos"] == 1


def test_confirmar_vai_pela_rpc_com_os_ids_lidos(api, emissor, banco, fatos_do_banco):
    fato = _fato()
    banco.responder("POST", "fatos_canonicos_transicionar", 200, 1)
    r = api.post(f"/api/v1/processos/{PROCESSO}/fatos-canonicos/confirmacao", headers=_auth(emissor),
                 json={"ids": [fato["id"]]})
    assert r.status_code == 200, r.text
    corpo = banco.corpo(next(c for c in banco.chamadas if c.url.path.endswith("fatos_canonicos_transicionar")))
    assert corpo == {"p_processo": PROCESSO, "p_substituir": [], "p_confirmar": [fato["id"]]}


@pytest.mark.parametrize("pg,status,codigo", [("PT409", 409, "FACTS_CHANGED"), ("42501", 403, "FORBIDDEN")])
def test_recusa_da_rpc_vira_erro_estavel(api, emissor, banco, fatos_do_banco, pg, status, codigo):
    banco.responder("POST", "fatos_canonicos_transicionar", 400, {"code": pg, "message": "x"})
    r = api.post(f"/api/v1/processos/{PROCESSO}/fatos-canonicos/confirmacao", headers=_auth(emissor),
                 json={"ids": [str(uuid.uuid4())]})
    assert r.status_code == status and r.json()["code"] == codigo


# ---------------------------------------------------------------------------
# Emissão: só leitura do que foi persistido
# ---------------------------------------------------------------------------
def _emissao():
    pacote = lambda dados: SimpleNamespace(payload=dados, content_hash=_sha(dados))  # noqa: E731
    return SimpleNamespace(id=str(uuid.uuid4()), docx_sha256=_sha(b"zip-docx"), pdf_sha256=_sha(b"zip-pdf"),
                           manifest={"documents": [{"tipo": "dfd", "revision": 2, "source_sha256": "a" * 64}]},
                           docx=pacote(b"zip-docx"), pdf=pacote(b"zip-pdf"))


def test_emissao_le_o_que_foi_gravado_e_entrega_o_pacote_exato(api, emissor, servico):
    emissao = _emissao()
    servico.emissao_atual = lambda pid: emissao
    r = api.get(f"/api/v1/processos/{PROCESSO}/emissao", headers=_auth(emissor))
    assert r.status_code == 200, r.text
    assert r.json()["documentos"] == [{"tipo": "dfd", "revisao": 2, "content_hash": "a" * 64}]
    r = api.get(f"/api/v1/processos/{PROCESSO}/emissao/pacote", params={"formato": "pdf"}, headers=_auth(emissor))
    assert r.status_code == 200 and r.content == b"zip-pdf"
    assert r.headers["content-type"] == "application/zip"
    assert r.headers["x-content-sha256"] == _sha(b"zip-pdf") and "no-store" in r.headers["cache-control"]


def test_sem_emissao_e_404(api, emissor, servico):
    servico.emissao_atual = lambda pid: None
    for caminho in ("emissao", "emissao/pacote?formato=docx"):
        r = api.get(f"/api/v1/processos/{PROCESSO}/{caminho}", headers=_auth(emissor))
        assert r.status_code == 404, caminho


def test_emissao_de_processo_fora_do_acesso_nao_chega_ao_motor(api, emissor, banco, servico):
    servico.emissao_atual = lambda pid: pytest.fail("o RLS decide antes do motor")
    banco.responder("GET", "processos", 200, [])
    assert api.get(f"/api/v1/processos/{PROCESSO}/emissao", headers=_auth(emissor)).status_code == 404
