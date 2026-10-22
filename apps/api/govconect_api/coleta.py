"""
Coleta de preços assíncrona (P04c): job no banco, aviso na fila, worker.

O fluxo:

1. `POST /precos/pesquisas/{id}/coleta` (Idempotency-Key) grava o job em
   `api_jobs` (0031) com o token do usuário, conta os itens a processar e
   põe um aviso na fila. Devolve **202** com o job — a requisição não
   espera fonte externa nenhuma.
2. O worker (`fila.py`) chama `processar_job`, que roda o passo
   REENTRANTE do domínio (`cotacoes.pesquisar_em_lote`, um item por vez)
   até não sobrar item. O ponto de retomada é o estado de cada item no
   banco: worker que cai no meio e recomeça não refaz o que já foi feito.
3. `GET /jobs/{id}` devolve estado e `feitos/total`, do banco.

**Por que o token do usuário viaja na fila.** As tabelas de preços (0021)
não dão escrita a mais ninguém, e o worker não tem credencial de servidor
— de propósito. O token vai no aviso com validade igual à dele (`expires`)
e fora do log (`argsrepr`); o Redis fica na rede interna (ADR-007). Quando
o token está para vencer, o job para com `SESSION_EXPIRED` e o usuário
recomeça: o que já foi coletado fica.
"""

from __future__ import annotations

import base64
import json
import logging
import re
import time
import uuid
from datetime import datetime, timezone
from typing import Callable, Protocol

from fastapi import APIRouter, Body, Depends, Header, Request, Response
from pydantic import BaseModel, ConfigDict

from src import db
from src.precos import cotacoes
from src.precos import repositorio as repo
from src.precos.execucao import A_PROCESSAR
from src.streamlit_opcional import sessao_da_requisicao

from .erros import ErroApi
from .precos import TABELA_ITENS, TABELA_PESQUISAS, exigir_precos_habilitado
from .seguranca import Identidade, exigir_identidade
from .supabase_rest import ClienteRest

_log = logging.getLogger("govconect_api")

TABELA_JOBS = "api_jobs"
_CHAVE = re.compile(r"^[A-Za-z0-9._:-]{8,128}$")
# Margem antes do `exp`: não começar um item que o token não vai terminar.
MARGEM_DO_TOKEN_S = 90
ESTADOS_FINAIS = ("succeeded", "failed", "cancelled")


class Job(BaseModel):
    id: str
    tipo: str
    recurso_id: str
    estado: str
    feitos: int
    total: int
    progresso: int          # 0–100, derivado; total 0 é 100 se terminou
    erro_codigo: str
    criado_em: str
    iniciado_em: str | None
    concluido_em: str | None


class PedidoDeColeta(BaseModel):
    model_config = ConfigDict(extra="forbid")
    modo: str = "manual"


def job_do_banco(linha: dict) -> Job:
    feitos, total = int(linha.get("feitos") or 0), int(linha.get("total") or 0)
    estado = str(linha.get("estado") or "")
    progresso = (100 if estado == "succeeded" else 0) if total == 0 \
        else min(100, feitos * 100 // total)
    return Job(id=str(linha["id"]), tipo=str(linha.get("tipo") or ""),
               recurso_id=str(linha.get("recurso_id") or ""), estado=estado,
               feitos=feitos, total=total, progresso=progresso,
               erro_codigo=str(linha.get("erro_codigo") or ""),
               criado_em=str(linha.get("criado_em") or ""),
               iniciado_em=linha.get("iniciado_em"), concluido_em=linha.get("concluido_em"))


def expiracao_do_token(token: str) -> float | None:
    """`exp` sem verificar assinatura — a API JÁ verificou ao aceitar o
    pedido; aqui só se decide quando parar antes de o token vencer."""
    try:
        carga = token.split(".")[1]
        return float(json.loads(base64.urlsafe_b64decode(carga + "=" * (-len(carga) % 4)))["exp"])
    except Exception:  # noqa: BLE001
        return None


class Fila(Protocol):
    def enfileirar(self, *, job_id: str, token: str, tenant_id: str,
                   auth_user_id: str, secretaria_id: str | None) -> None: ...


# ---------------------------------------------------------------------------
# Worker: o que roda fora da requisição
# ---------------------------------------------------------------------------
class ErroTransitorio(Exception):
    """Banco/rede: vale tentar de novo (o worker decide quantas vezes)."""


def _agora_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def atualizar_job(rest: ClienteRest, token: str, job_id: str, **campos) -> None:
    r = rest.requisitar(token, "PATCH", TABELA_JOBS, params={"id": f"eq.{job_id}"}, corpo=campos)
    if r.status not in (200, 204):
        raise ErroTransitorio(f"job não atualizado ({r.status})")


def processar_job(*, job_id: str, token: str, tenant_id: str, auth_user_id: str,
                  secretaria_id: str | None, rest: ClienteRest,
                  fontes: list | None = None,
                  agora: Callable[[], float] = time.time) -> str:
    """Executa (ou retoma) um job. Devolve o estado final gravado."""
    r = rest.requisitar(token, "GET", TABELA_JOBS, params={
        "select": "id,estado,recurso_id,parametros,tentativas,total", "id": f"eq.{job_id}"})
    if r.status != 200 or not r.dados:
        # Token vencido no caminho ou job invisível: nada a fazer, e nada
        # a gravar (sem token válido não há como escrever).
        _log.warning("job_inacessivel job=%s status=%s", job_id, r.status)
        return "failed"
    job = r.dados[0]
    if job["estado"] in ESTADOS_FINAIS:
        return job["estado"]      # aviso repetido pela fila: já resolvido

    expira = expiracao_do_token(token)
    pesquisa_id = str(job["recurso_id"])
    modo = (job.get("parametros") or {}).get("modo", "manual")
    total = int(job.get("total") or 0)
    atualizar_job(rest, token, job_id, estado="running", iniciado_em=_agora_iso(),
                  tentativas=int(job.get("tentativas") or 0) + 1)

    ctx = cotacoes.Contexto(auth_user_id=auth_user_id, secretaria_id=secretaria_id)
    tentados: set[str] = set()
    opcoes = {} if fontes is None else {"fontes": fontes}
    try:
        with sessao_da_requisicao(token, tenant_id):
            cotacoes._exigir_editavel(repo.obter_pesquisa(pesquisa_id))  # noqa: SLF001
            while True:
                if expira is not None and expira - agora() < MARGEM_DO_TOKEN_S:
                    atualizar_job(rest, token, job_id, estado="failed",
                                  erro_codigo="SESSION_EXPIRED", concluido_em=_agora_iso())
                    return "failed"
                _, restantes = cotacoes.pesquisar_em_lote(
                    ctx, pesquisa_id, modo=modo, tamanho=1, ja_tentados=tentados, **opcoes)
                feitos = min(len(tentados), total) if total else len(tentados)
                atualizar_job(rest, token, job_id, feitos=feitos)
                if restantes == 0:
                    break
    except cotacoes.CotacaoImutavel:
        atualizar_job(rest, token, job_id, estado="failed", erro_codigo="IMMUTABLE",
                      concluido_em=_agora_iso())
        return "failed"
    except cotacoes.ErroCotacao:
        atualizar_job(rest, token, job_id, estado="failed", erro_codigo="DOMAIN_RULE",
                      concluido_em=_agora_iso())
        return "failed"
    except db.ErroBanco as exc:
        raise ErroTransitorio("banco") from exc
    atualizar_job(rest, token, job_id, estado="succeeded", concluido_em=_agora_iso(),
                  feitos=total if total else len(tentados))
    return "succeeded"


# ---------------------------------------------------------------------------
# Rotas
# ---------------------------------------------------------------------------
def rotas() -> APIRouter:
    r = APIRouter(tags=["jobs"])

    def _rest(request: Request) -> ClienteRest:
        rest = getattr(request.app.state, "rest", None)
        if rest is None:
            raise ErroApi(503, "AUTH_UNAVAILABLE", "Autenticação indisponível neste ambiente")
        return rest

    @r.post("/precos/pesquisas/{pesquisa_id}/coleta", status_code=202, response_model=Job,
            dependencies=[Depends(exigir_precos_habilitado)],
            responses={200: {"model": Job, "description": "Repetição da mesma Idempotency-Key"},
                       404: {"description": "Inexistente ou fora do seu acesso"},
                       503: {"description": "Fila indisponível"}})
    def iniciar(pesquisa_id: uuid.UUID, request: Request, response: Response,
                pedido: PedidoDeColeta = Body(default_factory=PedidoDeColeta),
                idempotency_key: str = Header(..., alias="Idempotency-Key"),
                eu: Identidade = Depends(exigir_identidade)) -> Job:
        if not _CHAVE.fullmatch(idempotency_key):
            raise ErroApi(400, "INVALID_IDEMPOTENCY_KEY", "Idempotency-Key inválida")
        if pedido.modo not in cotacoes.MODOS:
            raise ErroApi(422, "VALIDATION_ERROR", "Modo de coleta desconhecido")
        rest = _rest(request)

        dono = rest.requisitar(eu.token, "GET", TABELA_PESQUISAS, params={
            "select": "id,auth_user_id,estado", "id": f"eq.{pesquisa_id}",
            "tenant_id": f"eq.{eu.tenant_id}", "limit": "1"})
        if dono.status != 200 or not dono.dados:
            raise ErroApi(404, "NOT_FOUND", "Recurso não encontrado")
        if eu.papel != "admin" and str(dono.dados[0].get("auth_user_id")) != eu.auth_user_id:
            raise ErroApi(403, "FORBIDDEN", "Acesso negado")

        itens = rest.requisitar(eu.token, "GET", TABELA_ITENS, params={
            "select": "id", "pesquisa_id": f"eq.{pesquisa_id}", "removido_em": "is.null",
            "estado": f"in.({','.join(sorted(A_PROCESSAR))})", "limit": "5000"})
        total = len(itens.dados or []) if itens.status == 200 else 0

        criado = rest.requisitar(eu.token, "POST", TABELA_JOBS, prefer="return=representation",
                                 corpo={"tenant_id": eu.tenant_id, "auth_user_id": eu.auth_user_id,
                                        "tipo": "coleta_precos", "recurso_id": str(pesquisa_id),
                                        "parametros": {"modo": pedido.modo}, "total": total,
                                        "idempotency_key": idempotency_key})
        if criado.status == 409 and criado.codigo_pg == "23505":
            existente = rest.requisitar(eu.token, "GET", TABELA_JOBS, params={
                "select": "*", "idempotency_key": f"eq.{idempotency_key}",
                "tenant_id": f"eq.{eu.tenant_id}", "limit": "1"})
            linha = (existente.dados or [None])[0] if existente.status == 200 else None
            if not linha or str(linha.get("recurso_id")) != str(pesquisa_id):
                raise ErroApi(409, "IDEMPOTENCY_KEY_REUSED",
                              "Idempotency-Key já usada com outro conteúdo")
            response.status_code = 200
            response.headers["Idempotent-Replayed"] = "true"
            return job_do_banco(linha)
        if criado.status != 201 or not criado.dados:
            raise ErroApi(400, "BAD_REQUEST", "Não foi possível registrar a coleta")
        linha = criado.dados[0]

        fila: Fila | None = getattr(request.app.state, "fila", None)
        try:
            if fila is None:
                raise RuntimeError("sem fila")
            fila.enfileirar(job_id=str(linha["id"]), token=eu.token, tenant_id=eu.tenant_id,
                            auth_user_id=eu.auth_user_id, secretaria_id=eu.secretaria_id)
        except Exception:  # noqa: BLE001 — qualquer falha da fila é a mesma para o usuário
            _log.warning("fila_indisponivel job=%s", linha["id"])
            atualizar_job(rest, eu.token, str(linha["id"]), estado="failed",
                          erro_codigo="QUEUE_UNAVAILABLE", concluido_em=_agora_iso())
            raise ErroApi(503, "QUEUE_UNAVAILABLE",
                          "Coleta indisponível no momento. Tente de novo em instantes.") from None
        response.headers["Location"] = f"/api/v1/jobs/{linha['id']}"
        return job_do_banco(linha)

    @r.get("/jobs/{job_id}", response_model=Job,
           responses={404: {"description": "Inexistente ou de outra pessoa"}})
    def consultar(job_id: uuid.UUID, request: Request,
                  eu: Identidade = Depends(exigir_identidade)) -> Job:
        r_ = _rest(request).requisitar(eu.token, "GET", TABELA_JOBS, params={
            "select": "*", "id": f"eq.{job_id}", "tenant_id": f"eq.{eu.tenant_id}", "limit": "1"})
        if r_.status != 200 or not r_.dados:
            raise ErroApi(404, "NOT_FOUND", "Recurso não encontrado")
        return job_do_banco(r_.dados[0])

    return r
