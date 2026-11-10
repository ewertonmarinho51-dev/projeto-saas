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
from pydantic import BaseModel, ConfigDict, Field

from src import db
from src.precos import cotacoes, pncp
from src.precos import repositorio as repo
from src.precos.execucao import (JANELA_MAXIMA_DIAS, modo_da_ultima_busca, precisa_de_busca,
                                 precisa_de_reprocesso)
from src.streamlit_opcional import sessao_da_requisicao

from .erros import ErroApi
from .precos import TABELA_ITENS, TABELA_PESQUISAS, exigir_precos_habilitado
from .seguranca import Identidade, exigir_identidade
from .supabase_rest import ClienteRest

_log = logging.getLogger("govconect_api")

TABELA_JOBS = "api_jobs"
TABELA_EVENTOS = "pesquisa_preco_eventos"
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
    # O que o job produziu, para a tela (0032): no relatório, nome,
    # tamanho, SHA-256 e validade do arquivo; na falha, a mensagem do
    # domínio. Só exibição — o download não lê daqui.
    resultado: dict = {}


class FiltrosDaBusca(BaseModel):
    """Os filtros da busca de UM item (o painel "Pesquisar preços" do GovDocs)."""
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    # Dentro da janela que a busca consulta de fato (`execucao.JANELA_MAXIMA_DIAS`).
    janela_dias: int = Field(default=180, ge=30, le=JANELA_MAXIMA_DIAS)
    uf: str = Field(default="", max_length=2)


class PedidoDeColeta(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    modo: str = "manual"
    # Com `item_id`, a coleta é de UM item, mesmo já pesquisado — a busca
    # de novo que o servidor pede, com termo e filtros. Sem ele, o lote.
    item_id: uuid.UUID | None = None
    termo: str = Field(default="", max_length=300)
    filtros: FiltrosDaBusca | None = None
    # Contratação similar CONHECIDA no PNCP (número de controle ou link do
    # edital): os resultados homologados dela entram como referências do
    # item, pelo mesmo pipeline (Lei 14.133, art. 23, § 1º, II). Só com
    # `item_id`. O que viaja para a fila é o endereço REMONTADO a partir dos
    # dígitos (`contratacao_canonica`), nunca o texto digitado.
    contratacao_pncp: str = Field(default="", max_length=300)
    # "Reprocessar pendentes" (lote): além do que nunca rodou, o item sem
    # preço proposto, com falha técnica ou com o CV para revisar
    # (`execucao.precisa_de_reprocesso`). Item concluído nunca entra.
    reprocessar: bool = False


def contratacao_canonica(entrada: str) -> str | None:
    """Link público do edital montado só com CNPJ, ano e sequencial lidos da
    entrada — ou `None` se ela não é número de controle nem link do PNCP."""
    controle = pncp.controle_da_entrada(entrada)
    if controle is None:
        return None
    cnpj, ano, sequencial = controle
    return pncp.URL_CONTRATACAO.format(cnpj=cnpj, ano=ano, sequencial=sequencial)


def _fonte_da_contratacao(entrada: str):
    """Ponto único de criação (as provas trocam por um dublê sem rede)."""
    return pncp.PNCPContratacao(entrada)


def _motor_de_termos():
    """Motor de IA para sugerir termos, só com a flag `precos_ia_termos`
    ligada e motor configurado. Falha de leitura = sem IA: a busca segue
    determinística (normalização, catálogo, sinônimos validados)."""
    from src import governanca
    from src.precos import semantica

    try:
        if not db.flag_ativa(governanca.FLAG_PRECOS_IA_TERMOS):
            return None
        return semantica.motor_do_projeto(finalidade="pesquisa_precos")
    except Exception:  # noqa: BLE001 — IA é opcional de verdade
        return None


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
               iniciado_em=linha.get("iniciado_em"), concluido_em=linha.get("concluido_em"),
               resultado=_resultado_exibivel(linha.get("resultado")))


_CAMPOS_DO_RESULTADO = {"nome": str, "mimetype": str, "tamanho": int, "sha256": str,
                        "hash_decisorio": str, "registrado": bool, "expira_em": str,
                        "mensagem": str, "documento": str, "bloqueios": int, "avisos": int,
                        "processados": int, "pendentes": int}
# Desfecho por item no lote (`cotacoes.DESFECHOS`) e o item do recorte que
# já estava resolvido quando a vez dele chegou.
JA_RESOLVIDO = "ja_resolvido"
DESFECHOS_DO_LOTE = frozenset(cotacoes.DESFECHOS) | {JA_RESOLVIDO}


def registro_do_lote(desfechos: dict[str, str]) -> dict:
    """O que o job do lote grava: o desfecho de CADA item (ponto de
    retomada) e o resumo que conta cada item uma vez."""
    resumo: dict[str, int] = {}
    for motivo in desfechos.values():
        resumo[motivo] = resumo.get(motivo, 0) + 1
    return {"itens": dict(desfechos), "resumo": resumo,
            "processados": len(desfechos),
            "pendentes": sum(1 for m in desfechos.values() if m in cotacoes.PENDENTES)}


def _resultado_exibivel(bruto) -> dict:
    """Só os campos conhecidos, com o tipo esperado: o dono pode reescrever
    `resultado` pelo PostgREST, e a API não repassa o que não entende."""
    if not isinstance(bruto, dict):
        return {}
    saida = {}
    for chave, tipo in _CAMPOS_DO_RESULTADO.items():
        valor = bruto.get(chave)
        if isinstance(valor, tipo) and not (tipo is int and isinstance(valor, bool)):
            saida[chave] = valor[:500] if isinstance(valor, str) else valor
    pendencias = bruto.get("pendencias")
    if isinstance(pendencias, list):
        saida["pendencias"] = [p[:200] for p in pendencias[:20] if isinstance(p, str)]
    resumo = bruto.get("resumo")
    if isinstance(resumo, dict):
        saida["resumo"] = {k: v for k, v in resumo.items()
                           if k in DESFECHOS_DO_LOTE and isinstance(v, int)
                           and not isinstance(v, bool) and v >= 0}
    return saida


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
                   auth_user_id: str, secretaria_id: str | None,
                   usuario_id: str = "", tarefa: str = "coleta") -> None: ...


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
        "select": "id,estado,recurso_id,parametros,tentativas,total,resultado",
        "id": f"eq.{job_id}"})
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
    parametros = job.get("parametros") or {}
    modo = parametros.get("modo", "manual")
    total = int(job.get("total") or 0)
    atualizar_job(rest, token, job_id, estado="running", iniciado_em=_agora_iso(),
                  tentativas=int(job.get("tentativas") or 0) + 1)

    ctx = cotacoes.Contexto(auth_user_id=auth_user_id, secretaria_id=secretaria_id)
    tentados: set[str] = set()
    desfechos: dict[str, str] = {}
    opcoes = {} if fontes is None else {"fontes": fontes}
    try:
        with sessao_da_requisicao(token, tenant_id):
            cotacoes._exigir_editavel(repo.obter_pesquisa(pesquisa_id))  # noqa: SLF001
            # A mesma estratégia de expansão no item avulso e no lote; a IA
            # só entra com a flag e motor disponível (`_motor_de_termos`).
            motor = _motor_de_termos()
            if motor is not None:
                from src.precos import expansao

                opcoes["motor_semantico"] = motor
                # um orçamento de IA para a execução inteira do job
                opcoes["orcamento_ia"] = expansao.Orcamento(expansao.ORCAMENTO_IA_POR_LOTE)
            if parametros.get("item_id"):
                # UM item, a pedido. O MODO decide a ampliação: a busca
                # manual ("Pesquisar preços") é do servidor — descrição e o
                # termo dele, nada além; a automática gera as variantes
                # sozinha (`expansao.Plano`).
                filtros = dict(parametros.get("filtros") or {})
                filtros.pop("literal", None)
                filtros["uf"] = (filtros.get("uf") or "").upper() or None
                filtros["literal"] = modo == "manual"
                opcoes_do_item = dict(opcoes)
                contratacao = str(parametros.get("contratacao_pncp") or "")
                if contratacao:
                    # As fontes de sempre MAIS a contratação informada: a mesma
                    # compra vista nos dois portais é fundida em `busca`.
                    base = (list(fontes) if fontes is not None
                            else cotacoes._fontes_padrao())  # noqa: SLF001
                    opcoes_do_item["fontes"] = [*base, _fonte_da_contratacao(contratacao)]
                resultado = cotacoes.pesquisar_item(
                    ctx, pesquisa_id, str(parametros["item_id"]), modo=modo,
                    termo=str(parametros.get("termo") or ""), filtros=filtros,
                    **opcoes_do_item)
                atualizar_job(rest, token, job_id, estado="succeeded", concluido_em=_agora_iso(),
                              feitos=1, resultado={"mensagem": str(resultado.mensagem)[:500]})
                return "succeeded"
            # O RECORTE do lote foi fixado na criação do job (`item_ids`): item
            # importado depois não entra nesta rodada. O desfecho de cada item
            # mora no próprio job (`resultado.itens`) — reentrega da fila ou
            # worker que caiu retoma sem refazer o que já tem desfecho.
            item_ids = parametros.get("item_ids")
            item_ids = [str(i) for i in item_ids] if isinstance(item_ids, list) else None
            reprocessar = bool(parametros.get("reprocessar"))
            anteriores = (job.get("resultado") or {}).get("itens") or {}
            desfechos = {str(k): str(v) for k, v in anteriores.items()
                         if str(v) in DESFECHOS_DO_LOTE} if isinstance(anteriores, dict) else {}
            tentados |= set(desfechos)
            while True:
                if expira is not None and expira - agora() < MARGEM_DO_TOKEN_S:
                    atualizar_job(rest, token, job_id, estado="failed",
                                  erro_codigo="SESSION_EXPIRED", concluido_em=_agora_iso(),
                                  resultado=registro_do_lote(desfechos))
                    return "failed"
                resultados, restantes = cotacoes.pesquisar_em_lote(
                    ctx, pesquisa_id, modo=modo, tamanho=1, ja_tentados=tentados,
                    item_ids=item_ids, reprocessar=reprocessar, **opcoes)
                for resultado in resultados:
                    desfechos[str(resultado.item_id)] = resultado.desfecho
                feitos = min(len(desfechos), total) if total else len(desfechos)
                atualizar_job(rest, token, job_id, feitos=feitos,
                              resultado=registro_do_lote(desfechos))
                if restantes == 0:
                    break
            # item do recorte que já não precisava de busca quando a vez dele
            # chegou (concluído pelo servidor no meio do lote): conta uma vez
            for item_id in item_ids or []:
                desfechos.setdefault(item_id, JA_RESOLVIDO)
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
                  feitos=total if total else len(tentados),
                  resultado=registro_do_lote(desfechos))
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

        parametros: dict = {"modo": pedido.modo}
        contratacao = None
        if pedido.contratacao_pncp:
            contratacao = contratacao_canonica(pedido.contratacao_pncp)
            if pedido.item_id is None or contratacao is None:
                raise ErroApi(422, "PNCP_CONTRACT_INVALID",
                              "Contratação do PNCP não reconhecida: informe o número de "
                              "controle (00000000000000-1-000000/2026) ou o link do edital, "
                              "na busca de um item.")
        if pedido.item_id is not None:
            alvo = rest.requisitar(eu.token, "GET", TABELA_ITENS, params={
                "select": "id,estado", "id": f"eq.{pedido.item_id}", "pesquisa_id": f"eq.{pesquisa_id}",
                "tenant_id": f"eq.{eu.tenant_id}", "removido_em": "is.null", "limit": "1"})
            if alvo.status != 200 or not alvo.dados:
                raise ErroApi(404, "NOT_FOUND", "Recurso não encontrado")
            if alvo.dados[0].get("estado") == "complete":
                raise ErroApi(409, "ITEM_COMPLETE",
                              "Item concluído: reabra o item, com o motivo, antes de pesquisar de novo.")
            parametros.update({"item_id": str(pedido.item_id), "termo": pedido.termo,
                               "filtros": (pedido.filtros or FiltrosDaBusca()).model_dump()})
            if contratacao:
                parametros["contratacao_pncp"] = contratacao
            total = 1
        else:
            # O mesmo critério do worker (`execucao.precisa_de_busca`), para a
            # barra não dizer "0 de 0" de um lote que vai trabalhar.
            itens = rest.requisitar(eu.token, "GET", TABELA_ITENS, params={
                "select": "id,estado,preco_estimado,estatisticas", "pesquisa_id": f"eq.{pesquisa_id}",
                "removido_em": "is.null", "limit": "5000"})
            ultimas: dict[str, str] = {}
            if pedido.modo == "automatico":
                buscas = rest.requisitar(eu.token, "GET", TABELA_EVENTOS, params={
                    "select": "item_id,criado_em,modo:payload->>modo", "pesquisa_id": f"eq.{pesquisa_id}",
                    "tipo": "in.(busca_concluida,busca_falhou)", "order": "criado_em.desc", "limit": "5000"})
                ultimas = modo_da_ultima_busca(buscas.dados or []) if buscas.status == 200 else {}
            # O RECORTE fixado aqui é o que o worker processa (`item_ids`), com
            # o mesmo critério: a barra conta exatamente os itens da rodada.
            recorte = [str(i.get("id")) for i in (itens.dados or []) if itens.status == 200
                       and (precisa_de_reprocesso(i) if pedido.reprocessar
                            else precisa_de_busca(i, pedido.modo, ultimas.get(str(i.get("id")))))]
            parametros["item_ids"] = recorte
            if pedido.reprocessar:
                parametros["reprocessar"] = True
            total = len(recorte)

        criado = rest.requisitar(eu.token, "POST", TABELA_JOBS, prefer="return=representation",
                                 corpo={"tenant_id": eu.tenant_id, "auth_user_id": eu.auth_user_id,
                                        "tipo": "coleta_precos", "recurso_id": str(pesquisa_id),
                                        "parametros": parametros, "total": total,
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
