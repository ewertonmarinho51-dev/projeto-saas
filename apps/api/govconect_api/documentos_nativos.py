"""
WordCraft Workspace na API (Issue #137): o editor nativo por HTTP.

Este módulo NÃO grava, valida, aprova nem exporta documento. O dono
documental é `src.documentos_editor.DocumentoService` (único, proibido
duplicar), e o contrato do navegador é a `Ponte` de `src.wordcraft_protocol`
— os mesmos que o Streamlit usa. O que existe aqui é só o que o Streamlit
fazia com `st.session_state` e o que HTTP exige a mais:

* a ponte de cada editor aberto vive NO SERVIDOR (`Sessoes`), amarrada a
  quem a abriu (auth_user_id + tenant do token verificado) e ao documento.
  O navegador só conhece o `instance_id` e o nonce dela; outra conta que
  adivinhe o id recebe 404, igual a sessão que não existe;
* o ACK de salvamento sai da ponte DEPOIS do commit CAS no banco
  (`confirmar_checkpoint` com o recibo do dono). O navegador nunca escolhe
  revisão, hash, tenant, processo nem status;
* aprovação exige a prova de canvas bloqueado que a própria ponte guardou
  (`canvas_bloqueado`), na revisão e hash correntes. Nenhum valor do corpo
  vira vínculo de aprovação.

Três travas de ativação: `GOVCONECT_WORDCRAFT_WORKSPACE` no ambiente (corte
global), a conta em `GOVCONECT_WORDCRAFT_WORKSPACE_CONTAS`, quando a lista
existir, E o tenant no canário `wordcraft_editor` (tenant_modulos). Falhou
uma, a rota não existe (404).

A API roda com UM worker (Dockerfile.api): a sessão em memória é deste
processo. Reiniciou a API, o navegador recebe 404 na sessão e reabre — o
documento persistido não muda, e o rascunho não confirmado continua no
canvas até a pessoa decidir.
"""

from __future__ import annotations

import base64
import logging
import secrets
import threading
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Literal

from fastapi import APIRouter, Depends, Query, Request, Response
from pydantic import BaseModel, ConfigDict, Field

from src import contexto, db, fatos
from src.config import adota_srp, sequencia_do_processo
from src.streamlit_opcional import sessao_da_requisicao

from .erros import ErroApi
from .escrita_documental import EscritaIndisponivel, escrita_documental
from .seguranca import Identidade, exigir_identidade

_log = logging.getLogger("govconect_api")

FLAG_CANARIO = "wordcraft_editor"
NAMESPACE = uuid.NAMESPACE_URL
# Mesma ordem e mesmos rótulos do Streamlit (`src.config.DOCUMENTOS`).
TIPOS = {
    "dfd": "Documento de Formalização da Demanda",
    "etp": "Estudo Técnico Preliminar",
    "mapa_riscos": "Mapa de Riscos",
    "tr": "Termo de Referência",
    "edital": "Minuta de Edital",
    "arp": "Minuta da Ata de Registro de Preços",
}
SIGLAS = {"dfd": "DFD", "etp": "ETP", "mapa_riscos": "Mapa de Riscos", "tr": "TR",
          "edital": "Edital", "arp": "ARP"}
SESSAO_OCIOSA_S = 45 * 60
MAX_SESSOES = 500
MAX_SESSOES_POR_DONO = 6
MIME = {"docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        "pdf": "application/pdf"}
SEM_CACHE = {"Cache-Control": "private, no-store"}


def id_do_documento(processo_id: str, tipo: str) -> str:
    """O mesmo id determinístico do Streamlit (`wordcraft_operacional._abrir`)."""
    return str(uuid.uuid5(NAMESPACE, "govconnect-document:" + processo_id + ":" + tipo))


def tipo_do_documento(processo_id: str, document_id: str) -> str | None:
    return next((t for t in TIPOS if id_do_documento(processo_id, t) == document_id), None)


# ---------------------------------------------------------------------------
# Motor: o dono documental e o runtime aprovado, carregados uma vez
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class Motor:
    servico: Any
    origem: str
    module_url: str
    wasm_url: str


def carregar_motor() -> Motor:
    """Runtime admitido por manifesto + dono documental. Falha = 503."""
    from src.documentos_editor import DocumentoService
    from src.wordcraft_runtime import carregar

    runtime = carregar()
    servico = DocumentoService(node=runtime.node, bundle=runtime.bundle,
                               manifest_sha256=runtime.manifest_sha256)
    return Motor(servico, runtime.origin, runtime.origin + runtime.module_url,
                 runtime.origin + runtime.wasm_url)


# ---------------------------------------------------------------------------
# Sessões do editor (a ponte de cada canvas aberto)
# ---------------------------------------------------------------------------
@dataclass
class Sessao:
    ponte: Any
    dono: tuple[str, str]
    processo_id: str
    tipo: str
    status: str
    tocada: float = field(default_factory=time.monotonic)
    trava: threading.Lock = field(default_factory=threading.Lock, repr=False)


class Sessoes:
    def __init__(self, relogio=time.monotonic) -> None:
        self._itens: dict[str, Sessao] = {}
        self._trava = threading.Lock()
        self._relogio = relogio

    def _podar(self) -> None:
        agora = self._relogio()
        for chave in [k for k, s in self._itens.items() if agora - s.tocada > SESSAO_OCIOSA_S]:
            del self._itens[chave]

    def guardar(self, sessao: Sessao) -> None:
        with self._trava:
            self._podar()
            minhas = sorted((s.tocada, k) for k, s in self._itens.items() if s.dono == sessao.dono)
            for _, chave in minhas[: max(0, len(minhas) - MAX_SESSOES_POR_DONO + 1)]:
                del self._itens[chave]
            if len(self._itens) >= MAX_SESSOES:
                raise ErroApi(503, "EDITOR_BUSY", "Muitos editores abertos agora. Tente de novo em instantes.")
            sessao.tocada = self._relogio()
            self._itens[sessao.ponte.instance_id] = sessao

    def obter(self, instance_id: str, dono: tuple[str, str], document_id: str) -> Sessao:
        with self._trava:
            self._podar()
            sessao = self._itens.get(instance_id)
            # Mesma resposta para "não existe", "expirou" e "é de outra conta".
            if sessao is None or sessao.dono != dono or sessao.ponte.document_id != document_id:
                raise ErroApi(404, "EDITOR_SESSION_NOT_FOUND",
                              "Sessão do editor encerrada. Reabra o documento.")
            sessao.tocada = self._relogio()
            return sessao

    def encerrar(self, instance_id: str, dono: tuple[str, str]) -> None:
        with self._trava:
            sessao = self._itens.get(instance_id)
            if sessao is not None and sessao.dono == dono:
                del self._itens[instance_id]


# ---------------------------------------------------------------------------
# Contrato
# ---------------------------------------------------------------------------
class _Entrada(BaseModel):
    model_config = ConfigDict(extra="forbid")


class DocumentoDoProcesso(BaseModel):
    id: str
    tipo: str
    sigla: str
    rotulo: str
    nativo: bool
    legado: bool
    revisao: int | None = None
    content_hash: str | None = None
    status: str | None = None


class DocumentosDoProcesso(BaseModel):
    processo_id: str
    escrita: bool
    documentos: list[DocumentoDoProcesso]


class MotorDoEditor(BaseModel):
    wasm_url: str


class PedidoDeSessao(_Entrada):
    processo_id: uuid.UUID


class Ack(BaseModel):
    request_id: str
    revision: int
    content_hash: str


class FalhaDeGravacao(BaseModel):
    request_id: str
    conflict: bool


class EstadoDoEditor(BaseModel):
    """Tudo o que o host nativo lê a cada resposta. Vem só da ponte do servidor."""

    instance_id: str
    session_id: str
    document_id: str
    nonce: str
    event_ack: int
    estado: str
    revision: int
    content_hash: str
    status: str
    escrita: bool
    ack: Ack | None = None
    save_error: FalhaDeGravacao | None = None
    control: dict[str, Any] | None = None
    bloqueado: bool = False
    falha_controle: str | None = None


class AberturaDoEditor(EstadoDoEditor):
    processo_id: str
    tipo: str
    sigla: str
    rotulo: str
    checkpoint_base64: str
    module_url: str
    wasm_url: str


class LoteDeEventos(_Entrada):
    # Estrutura de cada evento: quem confere é a ponte (`receber_lote`).
    events: list[dict[str, Any]] = Field(min_length=1, max_length=256)


class PedidoDeRestauracao(_Entrada):
    instance_id: uuid.UUID
    revisao_origem: int = Field(ge=1)


class RevisaoDoHistorico(BaseModel):
    revisao: int
    content_hash: str
    atual: bool
    status: str
    modo: str
    restauravel: bool


class Historico(BaseModel):
    document_id: str
    revisoes: list[RevisaoDoHistorico]


class FatoPendente(BaseModel):
    id: str
    path: str
    valor: Any = None
    campo: str
    confianca: float
    inferido: bool


class FatosDoProcesso(BaseModel):
    """O que a aprovação exige: todo fato vigente confirmado por uma pessoa."""

    total: int
    confirmados: int
    pendentes: list[FatoPendente]
    invalidos: int
    pronto: bool


class ConfirmacaoDeFatos(_Entrada):
    # A lista que a pessoa LEU: se entrou fato novo, a RPC responde conflito.
    ids: list[uuid.UUID] = Field(min_length=1, max_length=1000)


class DocumentoEmitido(BaseModel):
    tipo: str
    revisao: int
    content_hash: str


class EmissaoOficial(BaseModel):
    id: str
    docx_sha256: str
    pdf_sha256: str
    documentos: list[DocumentoEmitido]


class EmissaoRegistrada(EmissaoOficial):
    evento_id: str
    replayed: bool


class DocumentoParaEmissao(BaseModel):
    tipo: str
    sigla: str
    rotulo: str
    aprovado: bool
    status: str | None = None
    revisao: int | None = None
    content_hash: str | None = None


class ProntidaoDaEmissao(BaseModel):
    """O conjunto que o processo exige, decidido no servidor."""

    pronto: bool
    escrita: bool
    documentos: list[DocumentoParaEmissao]
    fora_da_sequencia: list[str]


class DocumentoConferido(_Entrada):
    tipo: str = Field(pattern=r"^[a-z][a-z0-9_]{0,31}$")
    revisao: int = Field(ge=1)
    content_hash: str = Field(pattern=r"^[0-9a-f]{64}$")


class ConferenciaDeEmissao(_Entrada):
    # As revisões e os hashes que a pessoa viu. Não escolhem nada: só provam
    # que o que vai ser emitido é o que ela conferiu.
    documentos: list[DocumentoConferido] = Field(min_length=1, max_length=32)


class AprovacaoRegistrada(BaseModel):
    id: str
    document_id: str
    revision: int
    content_hash: str
    status: str
    replayed: bool


# ---------------------------------------------------------------------------
# Rotas
# ---------------------------------------------------------------------------
def _estado(sessao: Sessao, escrita: bool) -> dict[str, Any]:
    p = sessao.ponte
    falha = p.falha_controle()
    return dict(instance_id=p.instance_id, session_id=p.session_id, document_id=p.document_id,
                nonce=p.nonce, event_ack=p.sequence, estado=p.state, revision=p.revision,
                content_hash=p.content_hash, status=sessao.status, escrita=escrita,
                ack=p.ack_persistido(), save_error=p.falha_pendente(),
                control=p.controle_pendente(), bloqueado=p.canvas_bloqueado() is not None,
                falha_controle=(falha or {}).get("reason"))


def _resumo_dos_fatos(vigentes: list[dict]) -> FatosDoProcesso:
    pendentes = [f for f in vigentes if f.get("status") == "extraido"]
    invalidos = sum(1 for f in vigentes if f.get("status") not in {"extraido", "confirmado"})
    confirmados = sum(1 for f in vigentes if f.get("status") == "confirmado")
    return FatosDoProcesso(
        total=len(vigentes), confirmados=confirmados, invalidos=invalidos,
        pronto=bool(vigentes) and not pendentes and not invalidos,
        pendentes=[FatoPendente(id=str(f["id"]), path=str(f.get("path") or ""), valor=f.get("valor"),
                                campo=str(f.get("fonte") or "").split(":", 1)[-1],
                                confianca=float(f.get("confianca") or 0),
                                inferido=str(f.get("fonte") or "").startswith(fatos.PREFIXO_INFERENCIA))
                   for f in pendentes])


def sessao_do_dominio(eu: Identidade):
    return sessao_da_requisicao(eu.token, eu.tenant_id, {
        "id": eu.usuario_id, "auth_user_id": eu.auth_user_id,
        "secretaria_id": eu.secretaria_id, "nome": ""})


def exigir_workspace(request: Request, eu: Identidade) -> None:
    cfg = request.app.state.config
    if not cfg.wordcraft_workspace or (cfg.wordcraft_contas and eu.auth_user_id not in cfg.wordcraft_contas):
        raise ErroApi(404, "MODULE_UNAVAILABLE", "Editor de documentos indisponível")
    with sessao_do_dominio(eu):
        if not contexto.modulo_em_rollout_aqui(FLAG_CANARIO):
            raise ErroApi(404, "MODULE_UNAVAILABLE", "Editor de documentos indisponível")


def motor_da_api(request: Request) -> Motor:
    motor = getattr(request.app.state, "motor_documental", None)
    if motor is None:
        with _trava_motor:
            motor = getattr(request.app.state, "motor_documental", None)
            if motor is None:
                try:
                    motor = carregar_motor()
                except Exception:  # noqa: BLE001 — runtime não admitido
                    _log.warning("wordcraft_runtime_indisponivel")
                    raise ErroApi(503, "WORDCRAFT_RUNTIME_UNAVAILABLE",
                                  "O motor do editor não está disponível neste ambiente.") from None
                request.app.state.motor_documental = motor
    return motor


def rotas() -> APIRouter:
    r = APIRouter(tags=["documentos"])

    def _config(request: Request):
        return request.app.state.config

    _sessao_do_dominio = sessao_do_dominio
    _exigir_workspace = exigir_workspace
    _motor = motor_da_api

    def _sessoes(request: Request) -> Sessoes:
        return request.app.state.sessoes_documentais

    def _escrita(request: Request) -> bool:
        cfg = _config(request)
        return bool(cfg.documentos_escrita_chave and cfg.supabase_url)

    def _gravar(request: Request):
        cfg = _config(request)
        fabrica = getattr(request.app.state, "fabrica_documental", None)
        kwargs = {"fabrica": fabrica} if fabrica is not None else {}
        return escrita_documental(cfg.supabase_url, cfg.documentos_escrita_chave, **kwargs)

    def _traduzir(erro: Exception) -> ErroApi:
        from src.documentos_editor import AcessoNegado, ConflitoDocumento, ErroDocumento

        if isinstance(erro, EscritaIndisponivel):
            return ErroApi(503, "DOCUMENT_WRITE_UNAVAILABLE",
                           "A gravação de documentos ainda não está liberada neste ambiente.")
        if isinstance(erro, AcessoNegado):
            return ErroApi(404, "NOT_FOUND", "Documento não encontrado")
        if isinstance(erro, ConflitoDocumento):
            return ErroApi(409, "DOCUMENT_CONFLICT", str(erro))
        if isinstance(erro, ErroDocumento):
            # Mensagens do dono são fixas e sem dado do pedido (ver `_execute`).
            return ErroApi(422, "DOCUMENT_REJECTED", str(erro))
        raise erro

    def _ids(processo_id: str, document_id: str) -> str:
        tipo = tipo_do_documento(processo_id, document_id)
        if tipo is None:
            raise ErroApi(404, "NOT_FOUND", "Documento não encontrado")
        return tipo

    def _processo(request: Request, eu: Identidade, processo_id: str, colunas: str = "id") -> dict:
        """O processo, pelo RLS e com o tenant do token. Antes do motor: fora do
        acesso é 404 mesmo com o runtime fora do ar."""
        rest = getattr(request.app.state, "rest", None)
        if rest is None:
            raise ErroApi(503, "AUTH_UNAVAILABLE", "Autenticação indisponível neste ambiente")
        resposta = rest.requisitar(eu.token, "GET", "processos", params={
            "select": colunas, "id": f"eq.{processo_id}", "tenant_id": f"eq.{eu.tenant_id}"})
        if resposta.status != 200:
            raise ErroApi(503, "DATABASE_UNAVAILABLE", "Banco indisponível")
        if not resposta.dados:
            raise ErroApi(404, "NOT_FOUND", "Recurso não encontrado")
        return resposta.dados[0]

    @r.get("/documentos/motor", response_model=MotorDoEditor,
           responses={404: {"description": "Editor desligado para quem chama"},
                      503: {"description": "Motor indisponível"}})
    def motor_do_editor(request: Request, eu: Identidade = Depends(exigir_identidade)) -> MotorDoEditor:
        """Onde está o motor aprovado, para a página baixá-lo sem esperar a sessão."""
        _exigir_workspace(request, eu)
        return MotorDoEditor(wasm_url=_motor(request).wasm_url)

    @r.get("/processos/{processo_id}/documentos", response_model=DocumentosDoProcesso,
           responses={404: {"description": "Processo fora do seu acesso ou editor desligado"}})
    def listar(processo_id: uuid.UUID, request: Request,
               eu: Identidade = Depends(exigir_identidade)) -> DocumentosDoProcesso:
        """Documentos do processo que o editor abre: nativos e legados importáveis."""
        _exigir_workspace(request, eu)
        pid = str(processo_id)
        rest = request.app.state.rest
        legados = _processo(request, eu, pid, "id,documentos").get("documentos") or {}
        heads = rest.requisitar(eu.token, "GET", "documentos_editor", params={
            "select": "id,tipo,revision,content_hash,status", "processo_id": f"eq.{pid}", "limit": "33"})
        if heads.status != 200:
            raise ErroApi(503, "DATABASE_UNAVAILABLE", "Banco indisponível")
        nativos = {h.get("tipo"): h for h in heads.dados or [] if isinstance(h, dict)}
        itens = []
        for tipo, rotulo in TIPOS.items():
            head = nativos.get(tipo)
            legado = isinstance(legados, dict) and isinstance(legados.get(tipo), str) and bool(legados[tipo])
            if head is None and not legado:
                continue
            esperado = id_do_documento(pid, tipo)
            if head is not None and head.get("id") != esperado:
                # Head fora do id determinístico: não é do contrato, não abre.
                continue
            itens.append(DocumentoDoProcesso(
                id=esperado, tipo=tipo, sigla=SIGLAS[tipo], rotulo=rotulo, nativo=head is not None,
                legado=legado, revisao=(head or {}).get("revision"),
                content_hash=(head or {}).get("content_hash"), status=(head or {}).get("status")))
        return DocumentosDoProcesso(processo_id=pid, escrita=_escrita(request), documentos=itens)

    @r.post("/documentos/{document_id}/sessoes", response_model=AberturaDoEditor,
            responses={404: {"description": "Documento fora do seu acesso ou editor desligado"},
                       503: {"description": "Motor ou gravação indisponível"}})
    def abrir(document_id: uuid.UUID, pedido: PedidoDeSessao, request: Request, response: Response,
              eu: Identidade = Depends(exigir_identidade)) -> AberturaDoEditor:
        """Abre um canvas: revisão persistida + ponte nova, só desta conta."""
        _exigir_workspace(request, eu)
        response.headers.update(SEM_CACHE)
        did, pid = str(document_id), str(pedido.processo_id)
        tipo = _ids(pid, did)
        _processo(request, eu, pid)
        motor = _motor(request)
        from src.documentos_editor import AcessoNegado
        from src.wordcraft_protocol import Ponte

        with _sessao_do_dominio(eu):
            try:
                try:
                    documento = motor.servico.abrir(did)
                except AcessoNegado:
                    # Ainda sem head nativo: importa o texto legado UMA vez
                    # (operação idempotente, a mesma chave do Streamlit).
                    if not _escrita(request):
                        raise EscritaIndisponivel("importação exige gravação") from None
                    operacao = str(uuid.uuid5(NAMESPACE, "govconnect-wordcraft-import:" + pid + ":" + tipo))
                    with _gravar(request):
                        documento = motor.servico.importar_legado(
                            processo_id=pid, tipo=tipo, operation_id=operacao, formato="markdown")
            except Exception as erro:  # noqa: BLE001
                raise _traduzir(erro) from None
        if (documento.id, documento.processo_id, documento.tipo) != (did, pid, tipo):
            raise ErroApi(404, "NOT_FOUND", "Documento não encontrado")
        ponte = Ponte(motor.origem, str(uuid.uuid4()), str(uuid.uuid4()), documento.id,
                      secrets.token_urlsafe(48), revision=documento.revision,
                      content_hash=documento.content_hash)
        sessao = Sessao(ponte, (eu.auth_user_id, eu.tenant_id), pid, tipo, documento.status)
        _sessoes(request).guardar(sessao)
        return AberturaDoEditor(
            **_estado(sessao, _escrita(request)), processo_id=pid, tipo=tipo, sigla=SIGLAS[tipo],
            rotulo=TIPOS[tipo], checkpoint_base64=base64.b64encode(documento.payload).decode("ascii"),
            module_url=motor.module_url, wasm_url=motor.wasm_url)

    @r.post("/documentos/{document_id}/sessoes/{instance_id}/eventos", response_model=EstadoDoEditor,
            responses={404: {"description": "Sessão encerrada"},
                       409: {"description": "Lote recusado pela ponte (replay, escopo, revisão)"}})
    def eventos(document_id: uuid.UUID, instance_id: uuid.UUID, lote: LoteDeEventos,
                request: Request, response: Response,
                eu: Identidade = Depends(exigir_identidade)) -> EstadoDoEditor:
        """Lote acumulado do host nativo. Checkpoint aceito → commit CAS → ACK."""
        _exigir_workspace(request, eu)
        response.headers.update(SEM_CACHE)
        from src.documentos_editor import ConflitoDocumento
        from src.wordcraft_protocol import ErroPonte

        sessao = _sessoes(request).obter(str(instance_id), (eu.auth_user_id, eu.tenant_id), str(document_id))
        escrita = _escrita(request)
        with sessao.trava:
            ponte = sessao.ponte
            try:
                # A origem é a da própria ponte: o transporte é o BFF autenticado,
                # e a prova de escopo é o nonce que só esta sessão recebeu.
                checkpoint = ponte.receber_lote({"events": lote.events}, origin=ponte.origin, source_ok=True)
            except ErroPonte as erro:
                raise ErroApi(409, "EDITOR_PROTOCOL_REJECTED", str(erro)) from None
            if checkpoint is not None:
                try:
                    if not escrita:
                        raise EscritaIndisponivel("credencial documental não provisionada")
                    motor = _motor(request)
                    with _sessao_do_dominio(eu), _gravar(request):
                        recibo = motor.servico.checkpoint(ponte.document_id, checkpoint)
                    ponte.confirmar_checkpoint(request_id=recibo.request_id, revision=recibo.revision,
                                               content_hash=recibo.content_hash)
                    sessao.status = "rascunho"
                except Exception as erro:  # noqa: BLE001 — bytes ficam pendentes para retry
                    ponte.falhar_checkpoint(request_id=checkpoint.request_id,
                                            conflict=isinstance(erro, ConflitoDocumento))
                    _log.info("wordcraft_checkpoint_falhou tipo=%s", type(erro).__name__)
            return EstadoDoEditor(**_estado(sessao, escrita))

    @r.get("/documentos/{document_id}/sessoes/{instance_id}", response_model=EstadoDoEditor,
           responses={404: {"description": "Sessão encerrada"}})
    def estado(document_id: uuid.UUID, instance_id: uuid.UUID, request: Request, response: Response,
               eu: Identidade = Depends(exigir_identidade)) -> EstadoDoEditor:
        _exigir_workspace(request, eu)
        response.headers.update(SEM_CACHE)
        sessao = _sessoes(request).obter(str(instance_id), (eu.auth_user_id, eu.tenant_id), str(document_id))
        with sessao.trava:
            return EstadoDoEditor(**_estado(sessao, _escrita(request)))

    @r.delete("/documentos/{document_id}/sessoes/{instance_id}", status_code=204)
    def encerrar(document_id: uuid.UUID, instance_id: uuid.UUID, request: Request,
                 eu: Identidade = Depends(exigir_identidade)) -> Response:
        _sessoes(request).encerrar(str(instance_id), (eu.auth_user_id, eu.tenant_id))
        return Response(status_code=204, headers=SEM_CACHE)

    @r.post("/documentos/{document_id}/sessoes/{instance_id}/bloqueio", response_model=EstadoDoEditor,
            responses={409: {"description": "Há edição não salva ou controle pendente"}})
    def bloquear(document_id: uuid.UUID, instance_id: uuid.UUID, request: Request, response: Response,
                 eu: Identidade = Depends(exigir_identidade)) -> EstadoDoEditor:
        """Pede ao canvas o congelamento da revisão salva (prova para aprovar)."""
        _exigir_workspace(request, eu)
        response.headers.update(SEM_CACHE)
        from src.wordcraft_protocol import ErroPonte

        sessao = _sessoes(request).obter(str(instance_id), (eu.auth_user_id, eu.tenant_id), str(document_id))
        with sessao.trava:
            try:
                sessao.ponte.solicitar_bloqueio(str(uuid.uuid4()))
            except ErroPonte as erro:
                raise ErroApi(409, "EDITOR_NOT_CLEAN", str(erro)) from None
            return EstadoDoEditor(**_estado(sessao, _escrita(request)))

    @r.post("/documentos/{document_id}/sessoes/{instance_id}/liberacao", response_model=EstadoDoEditor,
            responses={409: {"description": "Canvas não está bloqueado"}})
    def liberar(document_id: uuid.UUID, instance_id: uuid.UUID, request: Request, response: Response,
                eu: Identidade = Depends(exigir_identidade)) -> EstadoDoEditor:
        _exigir_workspace(request, eu)
        response.headers.update(SEM_CACHE)
        from src.wordcraft_protocol import ErroPonte

        sessao = _sessoes(request).obter(str(instance_id), (eu.auth_user_id, eu.tenant_id), str(document_id))
        with sessao.trava:
            prova = sessao.ponte.canvas_bloqueado()
            try:
                if prova is None:
                    raise ErroPonte("Canvas não está bloqueado.")
                sessao.ponte.liberar_bloqueio(prova["command_id"])
            except ErroPonte as erro:
                raise ErroApi(409, "EDITOR_NOT_FROZEN", str(erro)) from None
            return EstadoDoEditor(**_estado(sessao, _escrita(request)))

    @r.post("/documentos/{document_id}/sessoes/{instance_id}/aprovacao", response_model=AprovacaoRegistrada,
            responses={409: {"description": "Sem canvas bloqueado na revisão corrente"},
                       422: {"description": "O dono documental recusou (fatos, competência, gate)"},
                       503: {"description": "Gravação indisponível"}})
    def aprovar(document_id: uuid.UUID, instance_id: uuid.UUID, request: Request, response: Response,
                eu: Identidade = Depends(exigir_identidade)) -> AprovacaoRegistrada:
        """Aprova a revisão EXATA congelada no canvas. Competência: o banco decide."""
        _exigir_workspace(request, eu)
        response.headers.update(SEM_CACHE)
        from src.documentos_editor import VinculoAprovacao

        sessao = _sessoes(request).obter(str(instance_id), (eu.auth_user_id, eu.tenant_id), str(document_id))
        with sessao.trava:
            prova = sessao.ponte.canvas_bloqueado()
            if prova is None:
                raise ErroApi(409, "EDITOR_NOT_FROZEN", "Revise e bloqueie a revisão salva antes de aprovar.")
            vinculo = VinculoAprovacao(
                document_id=sessao.ponte.document_id, revision=prova["revision"],
                content_hash=prova["content_hash"],
                operation_id=str(uuid.uuid5(NAMESPACE, "govconnect-wordcraft-approval:" + sessao.ponte.document_id
                                            + ":" + str(prova["revision"]) + ":" + prova["content_hash"])))
            try:
                if not _escrita(request):
                    raise EscritaIndisponivel("credencial documental não provisionada")
                motor = _motor(request)
                with _sessao_do_dominio(eu), _gravar(request):
                    aprovacao = motor.servico.aprovar(vinculo)
            except Exception as erro:  # noqa: BLE001
                raise _traduzir(erro) from None
            sessao.status = aprovacao.status
            return AprovacaoRegistrada(id=aprovacao.id, document_id=aprovacao.document_id,
                                       revision=aprovacao.revision, content_hash=aprovacao.content_hash,
                                       status=aprovacao.status, replayed=aprovacao.replayed)

    def _transicionar_fatos(request: Request, eu: Identidade, processo_id: str,
                            substituir: list[str], confirmar: list[str]) -> None:
        resposta = request.app.state.rest.requisitar(
            eu.token, "POST", "rpc/fatos_canonicos_transicionar",
            corpo={"p_processo": processo_id, "p_substituir": substituir, "p_confirmar": confirmar})
        if resposta.status in (200, 204):
            return
        erros = {"42501": (403, "FORBIDDEN", "Só o titular do processo ou um administrador confirma fatos."),
                 "PT409": (409, "FACTS_CHANGED", "Os fatos mudaram desde a sua leitura. Recarregue e confira."),
                 "22023": (422, "VALIDATION_ERROR", "Lista de fatos inválida.")}
        status, codigo, mensagem = erros.get(resposta.codigo_pg or "", (503, "DATABASE_UNAVAILABLE", "Banco indisponível"))
        raise ErroApi(status, codigo, mensagem)

    @r.post("/processos/{processo_id}/fatos-canonicos/sincronizacao", response_model=FatosDoProcesso,
            responses={403: {"description": "Há fatos a gravar e quem chama não é o titular nem admin"},
                       404: {"description": "Processo fora do seu acesso ou editor desligado"}})
    def sincronizar_fatos(processo_id: uuid.UUID, request: Request, response: Response,
                          eu: Identidade = Depends(exigir_identidade)) -> FatosDoProcesso:
        """Extrai do Formulário Matriz persistido, versiona e devolve o que falta confirmar."""
        _exigir_workspace(request, eu)
        response.headers.update(SEM_CACHE)
        pid = str(processo_id)
        dados = _processo(request, eu, pid, "id,dados").get("dados") or {}
        with _sessao_do_dominio(eu):
            try:
                inserir, substituir = fatos.planejar_versionamento(
                    fatos.extrair_do_formulario(dados, pid), db.listar_fatos(pid, apenas_vigentes=False))
                if inserir:
                    db.salvar_fatos(inserir)
            except db.ErroBanco:
                # Sem política de INSERT é quem não é titular nem admin; quem decide é o RLS.
                raise ErroApi(403, "FORBIDDEN",
                              "Só o titular do processo ou um administrador sincroniza os fatos.") from None
            if substituir:
                _transicionar_fatos(request, eu, pid, substituir, [])
            return _resumo_dos_fatos(db.listar_fatos(pid))

    @r.post("/processos/{processo_id}/fatos-canonicos/confirmacao", response_model=FatosDoProcesso,
            responses={403: {"description": "Quem chama não é o titular nem admin"},
                       409: {"description": "A lista não é mais a que a pessoa leu"}})
    def confirmar_fatos(processo_id: uuid.UUID, pedido: ConfirmacaoDeFatos, request: Request,
                        response: Response, eu: Identidade = Depends(exigir_identidade)) -> FatosDoProcesso:
        """Confirmação humana dos fatos extraídos. O autor vem do JWT, no banco."""
        _exigir_workspace(request, eu)
        response.headers.update(SEM_CACHE)
        pid = str(processo_id)
        _processo(request, eu, pid)
        _transicionar_fatos(request, eu, pid, [], [str(i) for i in pedido.ids])
        with _sessao_do_dominio(eu):
            return _resumo_dos_fatos(db.listar_fatos(pid))

    @r.get("/documentos/{document_id}/historico", response_model=Historico,
           responses={404: {"description": "Documento fora do seu acesso"}})
    def historico(document_id: uuid.UUID, request: Request, response: Response,
                  processo_id: uuid.UUID = Query(...),
                  eu: Identidade = Depends(exigir_identidade)) -> Historico:
        """Revisões imutáveis persistidas (as 50 mais recentes)."""
        _exigir_workspace(request, eu)
        response.headers.update(SEM_CACHE)
        did = str(document_id)
        _ids(str(processo_id), did)
        _processo(request, eu, str(processo_id))
        motor = _motor(request)
        with _sessao_do_dominio(eu):
            try:
                dados = motor.servico.historico_revisoes(did)
            except Exception as erro:  # noqa: BLE001
                raise _traduzir(erro) from None
        atual = next((i["revision"] for i in dados["revisions"] if i["current"]), 0)
        return Historico(document_id=did, revisoes=[RevisaoDoHistorico(
            revisao=i["revision"], content_hash=i["contentHash"], atual=i["current"], status=i["status"],
            modo=i["indexMode"], restauravel=not i["current"] and 1 <= i["revision"] < atual)
            for i in dados["revisions"]])

    @r.post("/documentos/{document_id}/restauracao", response_model=AberturaDoEditor,
            responses={409: {"description": "Edição local pendente ou revisão mudou"},
                       503: {"description": "Gravação indisponível"}})
    def restaurar(document_id: uuid.UUID, pedido: PedidoDeRestauracao, request: Request,
                  response: Response, eu: Identidade = Depends(exigir_identidade)) -> AberturaDoEditor:
        """Revisão antiga vira revisão NOVA (CAS). O canvas é reaberto do head novo."""
        _exigir_workspace(request, eu)
        response.headers.update(SEM_CACHE)
        did = str(document_id)
        dono = (eu.auth_user_id, eu.tenant_id)
        sessoes = _sessoes(request)
        sessao = sessoes.obter(str(pedido.instance_id), dono, did)
        motor = _motor(request)
        from src.wordcraft_protocol import Ponte

        with sessao.trava:
            ponte = sessao.ponte
            if ponte.state not in {"ready", "saved"}:
                raise ErroApi(409, "EDITOR_NOT_CLEAN", "Salve a edição antes de restaurar uma revisão.")
            operacao = str(uuid.uuid5(NAMESPACE, "govconnect-wordcraft-restore:" + did + ":"
                                      + str(ponte.revision) + ":" + str(pedido.revisao_origem)))
            try:
                if not _escrita(request):
                    raise EscritaIndisponivel("credencial documental não provisionada")
                with _sessao_do_dominio(eu):
                    with _gravar(request):
                        recibo = motor.servico.restaurar(did, source_revision=pedido.revisao_origem,
                                                         expected_revision=ponte.revision, operation_id=operacao)
                    documento = motor.servico.abrir(did)
            except Exception as erro:  # noqa: BLE001
                raise _traduzir(erro) from None
            if (documento.revision, documento.content_hash) != (recibo.revision, recibo.content_hash):
                raise ErroApi(409, "DOCUMENT_CONFLICT", "O documento mudou durante a restauração. Reabra.")
            sessoes.encerrar(ponte.instance_id, dono)
        nova = Sessao(Ponte(motor.origem, str(uuid.uuid4()), str(uuid.uuid4()), documento.id,
                            secrets.token_urlsafe(48), revision=documento.revision,
                            content_hash=documento.content_hash),
                      dono, sessao.processo_id, sessao.tipo, documento.status)
        sessoes.guardar(nova)
        return AberturaDoEditor(
            **_estado(nova, _escrita(request)), processo_id=sessao.processo_id, tipo=sessao.tipo,
            sigla=SIGLAS[sessao.tipo], rotulo=TIPOS[sessao.tipo],
            checkpoint_base64=base64.b64encode(documento.payload).decode("ascii"),
            module_url=motor.module_url, wasm_url=motor.wasm_url)

    @r.get("/documentos/{document_id}/exportacao",
           responses={200: {"content": {MIME["docx"]: {}, MIME["pdf"]: {}}},
                      409: {"description": "A revisão pedida não é mais a corrente"}})
    def exportar(document_id: uuid.UUID, request: Request,
                 processo_id: uuid.UUID = Query(...),
                 formato: Literal["docx", "pdf"] = Query(...),
                 revisao: int = Query(..., ge=1),
                 content_hash: str = Query(..., pattern=r"^[0-9a-f]{64}$"),
                 eu: Identidade = Depends(exigir_identidade)) -> Response:
        """Exporta a revisão PERSISTIDA exata (rascunho; não é emissão oficial)."""
        _exigir_workspace(request, eu)
        did, pid = str(document_id), str(processo_id)
        tipo = _ids(pid, did)
        _processo(request, eu, pid)
        motor = _motor(request)
        with _sessao_do_dominio(eu):
            try:
                artefato = motor.servico.exportar(did, expected_revision=revisao,
                                                  content_hash=content_hash, formato=formato)
            except Exception as erro:  # noqa: BLE001
                raise _traduzir(erro) from None
        nome = f"{SIGLAS[tipo].lower().replace(' ', '-')}-revisao-{artefato.revision}.{formato}"
        return Response(content=artefato.payload, media_type=MIME[formato], headers={
            **SEM_CACHE, "Content-Disposition": f'attachment; filename="{nome}"',
            "X-Content-SHA256": artefato.content_hash, "X-Content-Type-Options": "nosniff"})

    def _conjunto_da_emissao(request: Request, eu: Identidade, pid: str) -> tuple[tuple[str, ...], dict]:
        """Os tipos que o processo exige (a mesma conta de `emitir_aprovados`) e as cabeças."""
        dados = _processo(request, eu, pid, "id,dados").get("dados") or {}
        heads = request.app.state.rest.requisitar(eu.token, "GET", "documentos_editor", params={
            "select": "id,tipo,revision,content_hash,status", "processo_id": f"eq.{pid}", "limit": "33"})
        if heads.status != 200:
            raise ErroApi(503, "DATABASE_UNAVAILABLE", "Banco indisponível")
        por_tipo = {h["tipo"]: h for h in heads.dados or [] if isinstance(h, dict)}
        tipos = sequencia_do_processo(dados, dict.fromkeys(por_tipo, True))
        if adota_srp(dados):
            tipos.append("arp")
        return tuple(tipos), por_tipo

    @r.get("/processos/{processo_id}/emissao/prontidao", response_model=ProntidaoDaEmissao,
           responses={404: {"description": "Processo fora do seu acesso ou editor desligado"}})
    def prontidao_da_emissao(processo_id: uuid.UUID, request: Request, response: Response,
                             eu: Identidade = Depends(exigir_identidade)) -> ProntidaoDaEmissao:
        """O que falta aprovar. Mostra as revisões e hashes que a pessoa confere antes de emitir."""
        _exigir_workspace(request, eu)
        response.headers.update(SEM_CACHE)
        tipos, por_tipo = _conjunto_da_emissao(request, eu, str(processo_id))
        documentos = []
        for tipo in tipos:
            head = por_tipo.get(tipo) or {}
            documentos.append(DocumentoParaEmissao(
                tipo=tipo, sigla=SIGLAS.get(tipo, tipo.upper()), rotulo=TIPOS.get(tipo, tipo),
                aprovado=head.get("status") in {"aprovado", "emitido"}, status=head.get("status"),
                revisao=head.get("revision"), content_hash=head.get("content_hash")))
        fora = sorted(set(por_tipo) - set(tipos))
        return ProntidaoDaEmissao(pronto=all(d.aprovado for d in documentos) and not fora,
                                  escrita=_escrita(request), documentos=documentos, fora_da_sequencia=fora)

    @r.post("/processos/{processo_id}/emissao", response_model=EmissaoRegistrada,
            responses={403: {"description": "Papel sem competência de publicação"},
                       409: {"description": "O que foi conferido não é mais o que está no banco"},
                       422: {"description": "Há documento sem aprovação nativa"},
                       503: {"description": "Gravação indisponível"}})
    def emitir(processo_id: uuid.UUID, pedido: ConferenciaDeEmissao, request: Request, response: Response,
               eu: Identidade = Depends(exigir_identidade)) -> EmissaoRegistrada:
        """Ato oficial e imutável: os dois pacotes viram snapshot e a trilha registra.

        Conjunto, revisões e competência saem do servidor e do banco. Repetir o
        mesmo pedido devolve a mesma emissão (`replayed`), com a chave do Streamlit.
        """
        _exigir_workspace(request, eu)
        response.headers.update(SEM_CACHE)
        from src.documentos_editor import AcessoNegado

        pid = str(processo_id)
        tipos, por_tipo = _conjunto_da_emissao(request, eu, pid)
        conferidos = {d.tipo: (d.revisao, d.content_hash) for d in pedido.documentos}
        atuais = {t: ((por_tipo.get(t) or {}).get("revision"), (por_tipo.get(t) or {}).get("content_hash"))
                  for t in tipos}
        if conferidos != atuais or set(por_tipo) != set(tipos):
            raise ErroApi(409, "DOCUMENT_CONFLICT",
                          "Os documentos mudaram desde a sua conferência. Confira de novo antes de emitir.")
        if any(por_tipo[t].get("status") not in {"aprovado", "emitido"} for t in tipos):
            raise ErroApi(422, "EMISSION_NOT_READY", "Todos os documentos precisam estar aprovados.")
        operacao = str(uuid.uuid5(NAMESPACE, "govconnect-wordcraft-emission:" + pid + ":"
                                  + ":".join(por_tipo[t]["content_hash"] for t in tipos)))
        try:
            if not _escrita(request):
                raise EscritaIndisponivel("credencial documental não provisionada")
            motor = _motor(request)
            with _sessao_do_dominio(eu), _gravar(request):
                emissao = motor.servico.emitir_aprovados(pid, tipos=tipos, operation_id=operacao)
        except AcessoNegado:
            raise ErroApi(403, "FORBIDDEN", "Seu papel não permite registrar a emissão oficial.") from None
        except Exception as erro:  # noqa: BLE001
            raise _traduzir(erro) from None
        return EmissaoRegistrada(id=emissao.id, docx_sha256=emissao.docx_sha256, pdf_sha256=emissao.pdf_sha256,
                                 evento_id=emissao.event_id, replayed=emissao.replayed,
                                 documentos=[DocumentoEmitido(tipo=d["tipo"], revisao=d["revision"],
                                                              content_hash=d["source_sha256"])
                                             for d in emissao.manifest["documents"]])

    def _emissao(request: Request, eu: Identidade, pid: str):
        _processo(request, eu, pid)
        motor = _motor(request)
        with _sessao_do_dominio(eu):
            try:
                return motor.servico.emissao_atual(pid)
            except Exception as erro:  # noqa: BLE001
                raise _traduzir(erro) from None

    @r.get("/processos/{processo_id}/emissao", response_model=EmissaoOficial,
           responses={404: {"description": "Sem emissão oficial, ou processo fora do seu acesso"}})
    def emissao_atual(processo_id: uuid.UUID, request: Request, response: Response,
                      eu: Identidade = Depends(exigir_identidade)) -> EmissaoOficial:
        """A emissão oficial persistida. Só lê: não reexporta nem emite."""
        _exigir_workspace(request, eu)
        response.headers.update(SEM_CACHE)
        emissao = _emissao(request, eu, str(processo_id))
        if emissao is None:
            raise ErroApi(404, "NOT_FOUND", "Este processo ainda não tem emissão oficial")
        return EmissaoOficial(id=emissao.id, docx_sha256=emissao.docx_sha256, pdf_sha256=emissao.pdf_sha256,
                              documentos=[DocumentoEmitido(tipo=d["tipo"], revisao=d["revision"],
                                                           content_hash=d["source_sha256"])
                                          for d in emissao.manifest["documents"]])

    @r.get("/processos/{processo_id}/emissao/pacote",
           responses={200: {"content": {"application/zip": {}}},
                      404: {"description": "Sem emissão oficial, ou processo fora do seu acesso"}})
    def pacote_da_emissao(processo_id: uuid.UUID, request: Request,
                          formato: Literal["docx", "pdf"] = Query(...),
                          eu: Identidade = Depends(exigir_identidade)) -> Response:
        """O pacote exato gravado na emissão, sem passar pelo motor de novo."""
        _exigir_workspace(request, eu)
        emissao = _emissao(request, eu, str(processo_id))
        if emissao is None:
            raise ErroApi(404, "NOT_FOUND", "Este processo ainda não tem emissão oficial")
        pacote = emissao.docx if formato == "docx" else emissao.pdf
        return Response(content=pacote.payload, media_type="application/zip", headers={
            **SEM_CACHE, "Content-Disposition": f'attachment; filename="emissao-{formato}.zip"',
            "X-Content-SHA256": pacote.content_hash, "X-Content-Type-Options": "nosniff"})

    return r


_trava_motor = threading.Lock()
