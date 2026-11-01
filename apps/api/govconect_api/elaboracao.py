"""
`/api/v1/processos/{id}/elaboracao` — elaboração automática de documentos.

O fluxo, no molde da coleta (P04c):

1. `GET` diz em que pé o processo está: cada documento da sequência, o
   próximo passo e o job em curso. Nada disso é guardado: sai de `processos`,
   dos heads nativos e de `api_jobs`, e por isso recarregar a página não
   perde nada;
2. `POST` confere o próximo documento, grava o job em `api_jobs` (0039) e põe
   um aviso na fila. Devolve **202** com o job: a requisição não espera IA;
3. o worker (`fila.py`) chama `processar_elaboracao`, que gera com o domínio
   (`src.elaboracao` → `llm.gerar_documento`) e substitui o documento em
   `processos.documentos` com o token do dono e CAS em `atualizado_em`.

**Revisão.** O worker não tem a credencial documental (ADR-011) nem o motor
nativo, e não precisa: o texto gerado fica onde o `DocumentoService` já sabe
importar, e a primeira abertura no editor cria a revisão 1. Aprovar continua
sendo ato humano, no editor, com a prova de canvas bloqueado.

**Cadeia aprovada.** A projeção de um documento nativo aprovado roda no
motor, que só existe na API. Por isso quem monta o contexto herdado é o
`POST`, e ele viaja em `api_jobs.parametros`, sob o RLS do dono, sem passar
pelo Redis.

**Duplicidade.** O índice parcial da 0039 impede dois jobs ativos da mesma
pessoa no mesmo processo: o segundo clique recebe o job do primeiro. Job
preso porque o worker morreu sai de cena depois de `ABANDONADO_S`.

Mesmas travas do editor (`exigir_workspace`): fora do canário a rota não
existe, porque sem o editor o documento gerado não teria onde ser revisado.
"""

from __future__ import annotations

import logging
import time
import uuid
from datetime import datetime

from fastapi import APIRouter, Body, Depends, Header, Request, Response
from pydantic import BaseModel, ConfigDict, Field

from src import db, elaboracao as dominio
from src import formulario_matriz as fm
from src.config import CHAVE_FLUXO_MAPA, sequencia_do_processo
from src.streamlit_opcional import sessao_da_requisicao, st

from .coleta import (Fila, Job, MARGEM_DO_TOKEN_S, TABELA_JOBS, ErroTransitorio, _CHAVE, _agora_iso,
                     atualizar_job, expiracao_do_token, job_do_banco)
from .documentos_nativos import (SIGLAS, TIPOS, exigir_workspace, id_do_documento, motor_da_api,
                                 sessao_do_dominio)
from .erros import ErroApi
from .processos import _COLUNAS
from .seguranca import Identidade, exigir_identidade
from .supabase_rest import ClienteRest

_log = logging.getLogger("govconect_api")

TIPO_JOB = "elaboracao_documento"
ATIVOS = ("queued", "running")
# Sem atualização nesse tempo, o job morreu: o pior caso de uma geração (180 s
# por tentativa, três tentativas, em cada modelo da cascata) fica abaixo disto.
ABANDONADO_S = 30 * 60
_COLUNAS_DO_JOB = ("id,tipo,recurso_id,estado,feitos,total,erro_codigo,criado_em,iniciado_em,"
                   "concluido_em,resultado,atualizado_em")


class DocumentoDaElaboracao(BaseModel):
    id: str
    tipo: str
    sigla: str
    rotulo: str
    situacao: str
    revisao: int | None = None


class ProximoPasso(BaseModel):
    acao: str
    tipo: str | None = None
    sigla: str | None = None


class Elaboracao(BaseModel):
    processo_id: str
    # Abrir o texto gerado no editor importa, e importar exige a credencial
    # documental da API (ADR-011).
    escrita: bool
    faltantes: list[str]
    documentos: list[DocumentoDaElaboracao]
    proximo: ProximoPasso
    # O job em curso, ou a falha do próximo documento. Geração concluída não
    # fica aqui: o resultado é o documento na lista.
    job: Job | None = None
    # O que a revisão automática achou no texto gerado e impede a aprovação.
    # Vale até a primeira edição salva: depois, o texto já é outro.
    bloqueios: int = 0
    pendencias: list[str] = []


class PedidoDeElaboracao(BaseModel):
    model_config = ConfigDict(extra="forbid")
    # O documento que a pessoa viu como próximo: se mudou, é conflito.
    tipo: str | None = Field(default=None, pattern=r"^[a-z][a-z0-9_]{0,31}$")


# ---------------------------------------------------------------------------
# Leituras
# ---------------------------------------------------------------------------
def _ler_processo(rest: ClienteRest, token: str, tenant_id: str, processo_id: str) -> dict | None:
    r = rest.requisitar(token, "GET", "processos", params={
        "select": _COLUNAS, "id": f"eq.{processo_id}", "tenant_id": f"eq.{tenant_id}", "limit": "1"})
    if r.status != 200:
        raise ErroTransitorio(f"processo não lido ({r.status})")
    return r.dados[0] if r.dados else None


def _cabecas(rest: ClienteRest, token: str, processo_id: str) -> dict[str, dict]:
    r = rest.requisitar(token, "GET", "documentos_editor", params={
        "select": "id,tipo,revision,status", "processo_id": f"eq.{processo_id}", "limit": "33"})
    if r.status != 200:
        raise ErroApi(503, "DATABASE_UNAVAILABLE", "Banco indisponível")
    # Head fora do id determinístico não é do contrato: não conta como revisão.
    return {h["tipo"]: h for h in r.dados or []
            if isinstance(h, dict) and h.get("tipo") in TIPOS
            and h.get("id") == id_do_documento(processo_id, h["tipo"])}


def _abandonado(linha: dict, agora: float) -> bool:
    try:
        return agora - datetime.fromisoformat(str(linha["atualizado_em"])).timestamp() > ABANDONADO_S
    except (KeyError, ValueError):
        return False


def _encerrar_abandonado(rest: ClienteRest, eu: Identidade, linha: dict) -> dict:
    r = rest.requisitar(eu.token, "PATCH", TABELA_JOBS, params={
        "id": f"eq.{linha['id']}", "estado": "in.(queued,running)", "select": _COLUNAS_DO_JOB},
        corpo={"estado": "failed", "erro_codigo": "ABANDONED", "concluido_em": _agora_iso()},
        prefer="return=representation")
    if r.status != 200 or not r.dados:
        return {**linha, "estado": "failed", "erro_codigo": "ABANDONED"}
    _log.warning("elaboracao_abandonada job=%s", linha["id"])
    return r.dados[0]


def _job_recente(rest: ClienteRest, eu: Identidade, processo_id: str,
                 agora=time.time) -> dict | None:
    r = rest.requisitar(eu.token, "GET", TABELA_JOBS, params={
        "select": _COLUNAS_DO_JOB, "tipo": f"eq.{TIPO_JOB}", "recurso_id": f"eq.{processo_id}",
        "tenant_id": f"eq.{eu.tenant_id}", "order": "criado_em.desc", "limit": "1"})
    linha = (r.dados or [None])[0] if r.status == 200 else None
    if linha is not None and linha.get("estado") in ATIVOS and _abandonado(linha, agora()):
        return _encerrar_abandonado(rest, eu, linha)
    return linha


def _panorama(rest: ClienteRest, eu: Identidade, linha: dict
              ) -> tuple[dict, dict[str, dict], list[dominio.SituacaoDoDocumento], dominio.Proximo, list[str]]:
    with sessao_do_dominio(eu):
        mapa = db.flag_ativa(dominio.FLAG_MAPA)
    processo = {**linha, "dados": dominio.com_fluxo(linha.get("dados"), linha.get("documentos"), mapa)}
    cabecas = _cabecas(rest, eu.token, str(linha["id"]))
    documentos = dominio.situacoes(processo, cabecas)
    faltantes = fm.faltantes(processo["dados"])
    return processo, cabecas, documentos, dominio.proximo_passo(documentos, faltantes), faltantes


def _contexto_herdado(request: Request, eu: Identidade, processo: dict, cabecas: dict[str, dict],
                      documentos: list[dominio.SituacaoDoDocumento], tipo: str) -> str | None:
    from src.documentos_editor import ErroDocumento

    pid, legados = str(processo["id"]), processo.get("documentos") or {}
    concluidos = [d.tipo for d in documentos if d.situacao in (dominio.APROVADO, dominio.EMITIDO)]
    with sessao_do_dominio(eu):
        textos = {}
        try:
            for doc in concluidos:
                textos[doc] = (motor_da_api(request).servico.texto_aprovado(id_do_documento(pid, doc))[1]
                               if doc in cabecas else legados.get(doc) or "")
        except ErroDocumento:
            raise ErroApi(409, "APPROVED_TEXT_UNAVAILABLE",
                          "Um documento aprovado não pôde ser lido. Reabra-o no editor e tente de novo.") from None
        return dominio.contexto_para(tipo, processo, textos)


# ---------------------------------------------------------------------------
# Worker: o que roda fora da requisição
# ---------------------------------------------------------------------------
def _versao(linha: dict) -> tuple:
    return (linha.get("dados"), linha.get("documentos"), linha.get("aprovados"))


def _nova_etapa(linha: dict, dados: dict, tipo: str) -> int:
    ordem = sequencia_do_processo(dados, linha.get("documentos"))
    atual = int(linha.get("etapa") or 0)
    return max(atual, ordem.index(tipo) + 1) if tipo in ordem else atual


def processar_elaboracao(*, job_id: str, token: str, tenant_id: str, auth_user_id: str,
                         secretaria_id: str | None, usuario_id: str, rest: ClienteRest,
                         agora=time.time) -> str:
    """Executa um job. Devolve o estado final gravado."""
    r = rest.requisitar(token, "GET", TABELA_JOBS, params={
        "select": "id,estado,recurso_id,parametros,tentativas,total", "id": f"eq.{job_id}"})
    if r.status != 200 or not r.dados:
        # Token vencido no caminho ou job invisível: não há com que escrever.
        _log.warning("job_inacessivel job=%s status=%s", job_id, r.status)
        return "failed"
    job = r.dados[0]
    if job["estado"] not in ATIVOS:
        return job["estado"]        # aviso repetido pela fila: já resolvido

    parametros = job.get("parametros") or {}
    processo_id, tipo = str(job["recurso_id"]), str(parametros.get("tipo") or "")
    total = int(job.get("total") or len(dominio.ESTAGIOS))

    def falhar(codigo: str, mensagem: str = "") -> str:
        atualizar_job(rest, token, job_id, estado="failed", erro_codigo=codigo, concluido_em=_agora_iso(),
                      resultado={"documento": tipo, "mensagem": mensagem[:500]})
        return "failed"

    expira = expiracao_do_token(token)
    if expira is not None and expira - agora() < MARGEM_DO_TOKEN_S:
        return falhar("SESSION_EXPIRED", "Sua sessão expirou antes de a elaboração começar.")
    atualizar_job(rest, token, job_id, estado="running", iniciado_em=_agora_iso(), feitos=0,
                  tentativas=int(job.get("tentativas") or 0) + 1)

    def etapa(nome: str) -> None:
        # Progresso é informação: falha ao gravá-lo não joga fora texto pago.
        try:
            atualizar_job(rest, token, job_id, feitos=dominio.ESTAGIOS.index(nome))
        except ErroTransitorio:
            _log.warning("job_sem_progresso job=%s", job_id)

    linha = _ler_processo(rest, token, tenant_id, processo_id)
    if linha is None:
        return falhar("NOT_FOUND", "Processo não encontrado.")
    if tipo in (linha.get("documentos") or {}):
        # A entrega anterior gravou e caiu antes de encerrar o job.
        atualizar_job(rest, token, job_id, estado="succeeded", feitos=total, concluido_em=_agora_iso(),
                      resultado={"documento": tipo})
        return "succeeded"

    dados = dict(linha.get("dados") or {})
    if parametros.get("mapa"):
        dados[CHAVE_FLUXO_MAPA] = True
    from src import llm

    try:
        with sessao_da_requisicao(token, tenant_id, {
                "id": usuario_id, "auth_user_id": auth_user_id, "secretaria_id": secretaria_id, "nome": ""}):
            st.session_state["processo_id"] = processo_id
            st.session_state["documentos"] = dict(linha.get("documentos") or {})
            st.session_state["processo_criado_em"] = linha.get("criado_em")
            elaborado = dominio.elaborar(tipo, dados, parametros.get("contexto"), processo_id, etapa)
    except llm.ErroGeracaoIA as erro:
        _log.warning("elaboracao_sem_motor job=%s", job_id)
        return falhar("AI_UNAVAILABLE", str(erro))
    except dominio.EscolhaDeFamilia:
        return falhar("FAMILY_CHOICE_REQUIRED",
                      "Há mais de um modelo possível para este documento. "
                      "Publique só um modelo aplicável na Governança e tente de novo.")
    except db.ErroBanco as exc:
        raise ErroTransitorio("banco") from exc
    except Exception as exc:  # noqa: BLE001 — sem detalhe: pode citar o conteúdo do processo
        _log.error("elaboracao_falhou job=%s tipo=%s", job_id, type(exc).__name__)
        return falhar("GENERATION_FAILED", "Não foi possível concluir o documento.")

    etapa("FINALIZANDO")
    atual = _ler_processo(rest, token, tenant_id, processo_id)
    if atual is None or _versao(atual) != _versao(linha):
        return falhar("CONTEXT_CHANGED", "O processo foi alterado durante a elaboração. Confira e tente de novo.")
    gravado = rest.requisitar(token, "PATCH", "processos", params={
        "select": "id", "id": f"eq.{processo_id}", "tenant_id": f"eq.{tenant_id}",
        "atualizado_em": f"eq.{atual.get('atualizado_em')}"},
        corpo={"documentos": {**(atual.get("documentos") or {}), **elaborado.documentos},
               "dados": dados, "etapa": _nova_etapa(atual, dados, tipo)},
        prefer="return=representation")
    if gravado.status in (401, 403):
        return falhar("FORBIDDEN", "Você não tem mais permissão para alterar este processo.")
    if gravado.status != 200:
        raise ErroTransitorio(f"documento não gravado ({gravado.status})")
    if not gravado.dados:
        return falhar("CONTEXT_CHANGED", "O processo foi alterado durante a elaboração. Confira e tente de novo.")
    atualizar_job(rest, token, job_id, estado="succeeded", feitos=total, concluido_em=_agora_iso(),
                  resultado={"documento": tipo, "bloqueios": elaborado.bloqueios, "avisos": elaborado.avisos,
                             "pendencias": list(elaborado.pendencias)})
    _log.info("elaboracao_concluida job=%s documento=%s", job_id, tipo)
    return "succeeded"


# ---------------------------------------------------------------------------
# Rotas
# ---------------------------------------------------------------------------
def _exibivel(linha: dict | None, proximo: dominio.Proximo) -> Job | None:
    if linha is None:
        return None
    if linha.get("estado") in ATIVOS:
        return job_do_banco(linha)
    # Falha de documento que já saiu da frente não é mais notícia.
    documento = (linha.get("resultado") or {}).get("documento")
    if linha.get("estado") == "failed" and documento == proximo.tipo and proximo.acao == dominio.ELABORAR:
        return job_do_banco(linha)
    return None


def _achados(linha: dict | None, documentos: list[dominio.SituacaoDoDocumento],
             proximo: dominio.Proximo) -> tuple[int, list[str]]:
    """Bloqueios do último job, enquanto o documento dele for o texto gerado."""
    if linha is None or proximo.acao != dominio.REVISAR or linha.get("estado") != "succeeded":
        return 0, []
    resultado = job_do_banco(linha).resultado
    atual = next((d for d in documentos if d.tipo == proximo.tipo), None)
    if resultado.get("documento") != proximo.tipo or atual is None or (atual.revisao or 1) > 1:
        return 0, []
    return int(resultado.get("bloqueios") or 0), list(resultado.get("pendencias") or [])


def rotas() -> APIRouter:
    r = APIRouter(prefix="/processos", tags=["elaboracao"])

    def _rest(request: Request) -> ClienteRest:
        rest = getattr(request.app.state, "rest", None)
        if rest is None:
            raise ErroApi(503, "AUTH_UNAVAILABLE", "Autenticação indisponível neste ambiente")
        return rest

    def _processo(rest: ClienteRest, eu: Identidade, pid: str) -> dict:
        try:
            linha = _ler_processo(rest, eu.token, eu.tenant_id, pid)
        except ErroTransitorio:
            raise ErroApi(503, "DATABASE_UNAVAILABLE", "Banco indisponível") from None
        if linha is None:
            # 404 também para o de outro município: não confirma que existe.
            raise ErroApi(404, "NOT_FOUND", "Recurso não encontrado")
        return linha

    @r.get("/{processo_id}/elaboracao", response_model=Elaboracao,
           responses={404: {"description": "Processo fora do seu acesso ou editor desligado"}})
    def consultar(processo_id: uuid.UUID, request: Request, response: Response,
                  eu: Identidade = Depends(exigir_identidade)) -> Elaboracao:
        """Em que pé está cada documento, e o que fazer agora."""
        exigir_workspace(request, eu)
        response.headers["Cache-Control"] = "private, no-store"
        rest, pid = _rest(request), str(processo_id)
        linha = _processo(rest, eu, pid)
        _, _, documentos, proximo, faltantes = _panorama(rest, eu, linha)
        cfg = request.app.state.config
        recente = _job_recente(rest, eu, pid)
        bloqueios, pendencias = _achados(recente, documentos, proximo)
        return Elaboracao(
            processo_id=pid, escrita=bool(cfg.documentos_escrita_chave and cfg.supabase_url), faltantes=faltantes,
            documentos=[DocumentoDaElaboracao(id=id_do_documento(pid, d.tipo), tipo=d.tipo, sigla=SIGLAS[d.tipo],
                                              rotulo=TIPOS[d.tipo], situacao=d.situacao, revisao=d.revisao)
                        for d in documentos],
            proximo=ProximoPasso(acao=proximo.acao, tipo=proximo.tipo,
                                 sigla=SIGLAS.get(proximo.tipo or "")),
            job=_exibivel(recente, proximo), bloqueios=bloqueios, pendencias=pendencias)

    @r.post("/{processo_id}/elaboracao", status_code=202, response_model=Job,
            responses={200: {"model": Job, "description": "Já havia elaboração em curso: é o mesmo job"},
                       403: {"description": "Só o titular do processo ou um administrador"},
                       404: {"description": "Processo fora do seu acesso ou editor desligado"},
                       409: {"description": "Não há documento a elaborar agora, ou o próximo mudou"},
                       422: {"description": "Faltam dados obrigatórios do formulário"},
                       503: {"description": "Fila indisponível"}})
    def iniciar(processo_id: uuid.UUID, request: Request, response: Response,
                pedido: PedidoDeElaboracao = Body(default_factory=PedidoDeElaboracao),
                idempotency_key: str = Header(..., alias="Idempotency-Key"),
                eu: Identidade = Depends(exigir_identidade)) -> Job:
        """Põe na fila o próximo documento. Quem escolhe qual é o servidor."""
        exigir_workspace(request, eu)
        if not _CHAVE.fullmatch(idempotency_key):
            raise ErroApi(400, "INVALID_IDEMPOTENCY_KEY", "Idempotency-Key inválida")
        rest, pid = _rest(request), str(processo_id)
        linha = _processo(rest, eu, pid)
        # Espelha `processos_edita`: o dono ou o admin. O RLS é quem garante.
        if eu.papel != "admin" and linha.get("auth_user_id") != eu.auth_user_id:
            raise ErroApi(403, "FORBIDDEN", "Acesso negado")

        recente = _job_recente(rest, eu, pid)
        if recente is not None and recente.get("estado") in ATIVOS:
            response.status_code = 200
            return job_do_banco(recente)

        processo, cabecas, documentos, proximo, faltantes = _panorama(rest, eu, linha)
        if proximo.acao == dominio.FORMULARIO:
            raise ErroApi(422, "VALIDATION_ERROR", "Preencha os campos obrigatórios: " + ", ".join(faltantes) + ".")
        if proximo.acao != dominio.ELABORAR or (pedido.tipo and pedido.tipo != proximo.tipo):
            raise ErroApi(409, "NOT_NEXT_DOCUMENT", "Este não é o próximo documento do processo. Recarregue a página.")
        tipo = str(proximo.tipo)

        criado = rest.requisitar(eu.token, "POST", TABELA_JOBS, prefer="return=representation", corpo={
            "tenant_id": eu.tenant_id, "auth_user_id": eu.auth_user_id, "tipo": TIPO_JOB, "recurso_id": pid,
            "parametros": {"tipo": tipo, "mapa": CHAVE_FLUXO_MAPA in processo["dados"],
                           "contexto": _contexto_herdado(request, eu, processo, cabecas, documentos, tipo)},
            "resultado": {"documento": tipo}, "total": len(dominio.ESTAGIOS),
            "idempotency_key": idempotency_key})
        if criado.status == 409 and criado.codigo_pg == "23505":
            # Duas abas ao mesmo tempo: quem perdeu a corrida acompanha a outra.
            existente = _job_recente(rest, eu, pid)
            if existente is None:
                raise ErroApi(409, "IDEMPOTENCY_KEY_REUSED", "Idempotency-Key já usada com outro conteúdo")
            response.status_code = 200
            return job_do_banco(existente)
        if criado.status != 201 or not criado.dados:
            raise ErroApi(400, "BAD_REQUEST", "Não foi possível registrar a elaboração")
        job = criado.dados[0]

        fila: Fila | None = getattr(request.app.state, "fila", None)
        try:
            if fila is None:
                raise RuntimeError("sem fila")
            fila.enfileirar(job_id=str(job["id"]), token=eu.token, tenant_id=eu.tenant_id,
                            auth_user_id=eu.auth_user_id, secretaria_id=eu.secretaria_id,
                            usuario_id=eu.usuario_id or "", tarefa="elaboracao")
        except Exception:  # noqa: BLE001 — qualquer falha da fila é a mesma para o usuário
            _log.warning("fila_indisponivel job=%s", job["id"])
            atualizar_job(rest, eu.token, str(job["id"]), estado="failed",
                          erro_codigo="QUEUE_UNAVAILABLE", concluido_em=_agora_iso())
            raise ErroApi(503, "QUEUE_UNAVAILABLE",
                          "Elaboração indisponível no momento. Tente de novo em instantes.") from None
        response.headers["Location"] = f"/api/v1/jobs/{job['id']}"
        return job_do_banco(job)

    return r
