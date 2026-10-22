"""
Emissão dos relatórios da pesquisa de preços (P04d): ciência, job, download.

A regra é a do Streamlit, chamada do mesmo lugar (`src/precos/emissao.py`
e `src/precos/ciencia.py`). Esta camada só traduz HTTP ↔ domínio e põe a
geração na fila:

    GET  /precos/pesquisas/{id}/emissao   o que a emissão vai pedir: alertas,
                                          pendências, ciência já dada, opções
    POST /precos/pesquisas/{id}/ciencia   "Estou ciente" (revalida a cesta)
    POST /precos/pesquisas/{id}/relatorios  202 + job; o worker gera
    GET  /jobs/{id}/artefato              o arquivo, ao dono do job, 30 min

**Ciência (pacote Jev, RF-03).** Preço atípico não trava o relatório; o
servidor exige CIÊNCIA desta versão da cesta, por esta pessoa. O worker
confere de novo na hora de gerar (`ciencia.exigir`) — o pedido sozinho,
de outra aba ou de um script, não emite sem ela.

**Flags.** A emissão pela API só existe com a ciência ligada
(`precos_ciencia_emissao`, ligada em produção desde a v1.9.6). Com ela
desligada, o Streamlit usa o aviso de pendências antigo, que bloqueia; a
API não o reimplementa — responde 409 e a tela diz para emitir pelo app
de sempre. A flag do relatório visual escolhe os formatos, igual à tela.
Flag ilegível é 503, nunca "desligada" (0033).

**Quem emite.** Quem LÊ a pesquisa (0029: "emite quem lê"); registrar a
ciência, só quem ESCREVE nela (0021: dono ou admin) — a trilha recusaria.
"""

from __future__ import annotations

import logging
import re
import time
import urllib.parse
import uuid
from typing import Literal

from fastapi import APIRouter, Body, Depends, Header, Request, Response
from pydantic import BaseModel, ConfigDict, Field

from src import db, governanca
from src.precos import ciencia, emissao, relatorio
from src.precos import repositorio as repo
from src.precos.documento_cotacao import ErroDeRenderizacao
from src.streamlit_opcional import sessao_da_requisicao

from . import artefatos
from .coleta import (TABELA_JOBS, ErroTransitorio, Fila, Job, _agora_iso,
                     atualizar_job, job_do_banco)
from .erros import ErroApi
from .precos import TABELA_PESQUISAS, Valor, exigir_precos_habilitado, valor_monetario
from .seguranca import Identidade, exigir_identidade
from .supabase_rest import ClienteRest

_log = logging.getLogger("govconect_api")

TIPO_DO_JOB = "relatorio_precos"
_CHAVE = re.compile(r"^[A-Za-z0-9._:-]{8,128}$")
_ASSINATURA = re.compile(r"^[0-9a-f]{64}$")

TipoDeRelatorio = Literal["cotacao", "analitico_integral", "completo", "resumido",
                          "analitico", "pacote"]
FormatoDeRelatorio = Literal["pdf", "docx", "xlsx", "zip"]

# (tipo, formato) que cada gerador oferece — os mesmos botões da tela.
OPCOES_VISUAIS = (("cotacao", "pdf", "Relatório de Cotação (PDF)"),
                  ("cotacao", "docx", "Relatório de Cotação (DOCX)"),
                  ("analitico", "xlsx", "Memória analítica (XLSX)"),
                  ("analitico_integral", "pdf", "Relatório Analítico Integral (PDF)"),
                  ("pacote", "zip", "Pacote completo (ZIP)"))
OPCOES_LEGADAS = (("completo", "pdf", "Relatório completo (PDF)"),
                  ("completo", "docx", "Relatório completo (DOCX)"),
                  ("resumido", "pdf", "Quadro resumido (PDF)"),
                  ("resumido", "docx", "Quadro resumido (DOCX)"),
                  ("analitico", "xlsx", "Memória analítica (XLSX)"),
                  ("pacote", "zip", "Pacote completo (ZIP)"))


# ---------------------------------------------------------------------------
# Contratos
# ---------------------------------------------------------------------------
class AlertaDePreco(BaseModel):
    numero: int
    descricao: str
    valor: Valor | None
    origem: str
    mensagem: str


class PendenciaDeItem(BaseModel):
    numero: int
    descricao: str
    deficiencias: list[str]


class OpcaoDeRelatorio(BaseModel):
    tipo: str
    formato: str
    rotulo: str


class CienciaRegistrada(BaseModel):
    registrada_em: str
    assinatura: str


class PreparoDaEmissao(BaseModel):
    # False: a API não emite (flag da ciência desligada) — `motivo` diz por quê.
    disponivel: bool
    motivo: str
    # Identificador decisório desta versão do resultado (o que o PDF imprime).
    identificador: str
    # A cesta está acima do teto: nenhum relatório sai até refazer a cotação.
    bloqueio: str
    requer_ciencia: bool
    assinatura: str
    alertas: list[AlertaDePreco]
    pendencias: list[PendenciaDeItem]
    ciencia: CienciaRegistrada | None
    # Pode registrar a ciência (dono da pesquisa ou admin).
    pode_registrar_ciencia: bool
    opcoes: list[OpcaoDeRelatorio]
    total_referencias: int


class PedidoDeCiencia(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    assinatura: str = Field(min_length=64, max_length=64)


class PedidoDeRelatorio(BaseModel):
    model_config = ConfigDict(extra="forbid")
    tipo: TipoDeRelatorio
    formato: FormatoDeRelatorio
    com_integral: bool = False


# ---------------------------------------------------------------------------
# Domínio, dentro da sessão do usuário
# ---------------------------------------------------------------------------
def _usuario(eu_ou_ids: dict) -> dict:
    """O `session_state["usuario"]` que `contexto` e o timbrado leem."""
    return {k: eu_ou_ids.get(k) for k in ("id", "auth_user_id", "secretaria_id", "nome")}


def _carregar(pesquisa_id: str, tenant_id: str) -> tuple[dict, list[dict], dict]:
    """Pesquisa, itens ativos e referências — os MESMOS da tela (a assinatura
    da ciência só bate se os dados forem lidos do mesmo jeito)."""
    pesquisa = repo.obter_pesquisa(pesquisa_id)
    if not pesquisa or str(pesquisa.get("tenant_id") or tenant_id) != tenant_id:
        raise ErroApi(404, "NOT_FOUND", "Recurso não encontrado")
    itens = [i for i in repo.listar_itens(pesquisa_id) if not i.get("removido_em")]
    referencias = {str(i["id"]): repo.listar_referencias(str(i["id"])) for i in itens}
    return pesquisa, itens, referencias


def _flags() -> tuple[bool, bool]:
    """(ciência ligada, relatório visual ligado). Ilegível: ErroBanco."""
    return (db.flag_ativa(governanca.FLAG_CIENCIA_EMISSAO),
            db.flag_ativa(governanca.FLAG_RELATORIO_VISUAL))


def opcoes(visual: bool, total_referencias: int) -> list[tuple[str, str, str]]:
    if not visual:
        return list(OPCOES_LEGADAS)
    return [o for o in OPCOES_VISUAIS
            if o[0] != "analitico_integral" or total_referencias <= emissao.LIMITE_DO_ANALITICO]


def _traduzir(exc: Exception) -> ErroApi:
    if isinstance(exc, repo.SemSessao):
        return ErroApi(401, "UNAUTHENTICATED", "Sessão ausente, expirada ou inválida",
                       {"WWW-Authenticate": "Bearer"})
    return ErroApi(503, "DATABASE_UNAVAILABLE", "Banco de dados indisponível")


SEM_CIENCIA = ("A emissão pela nova interface exige a confirmação de alertas "
               "(ciência na emissão), que está desligada. Emita pelo aplicativo "
               "de sempre.")


# ---------------------------------------------------------------------------
# Worker
# ---------------------------------------------------------------------------
def _falhar(rest, token, job_id, codigo, mensagem="") -> str:
    atualizar_job(rest, token, job_id, estado="failed", erro_codigo=codigo,
                  concluido_em=_agora_iso(),
                  resultado={"mensagem": mensagem[:500]} if mensagem else {})
    return "failed"


def _nome_de(rest: ClienteRest, token: str, auth_user_id: str) -> str:
    r = rest.requisitar(token, "GET", "usuarios", params={
        "select": "nome", "auth_user_id": f"eq.{auth_user_id}", "limit": "1"})
    linha = (r.dados or [{}])[0] if r.status == 200 else {}
    return str(linha.get("nome") or "").strip() or "usuário autenticado"


def processar_relatorio(*, job_id: str, token: str, tenant_id: str, auth_user_id: str,
                        secretaria_id: str | None, usuario_id: str, rest: ClienteRest,
                        deposito: artefatos.Deposito) -> str:
    """Gera o relatório de um job, guarda o arquivo e registra a emissão."""
    r = rest.requisitar(token, "GET", TABELA_JOBS, params={
        "select": "id,estado,tipo,recurso_id,parametros,tentativas", "id": f"eq.{job_id}"})
    if r.status != 200 or not r.dados:
        _log.warning("job_inacessivel job=%s status=%s", job_id, r.status)
        return "failed"
    job = r.dados[0]
    if job["estado"] in ("succeeded", "failed", "cancelled"):
        return job["estado"]
    if job.get("tipo") != TIPO_DO_JOB:
        return _falhar(rest, token, job_id, "INVALID_REPORT")
    parametros = job.get("parametros") or {}
    tipo, formato = str(parametros.get("tipo") or ""), str(parametros.get("formato") or "")
    com_integral = bool(parametros.get("com_integral"))
    atualizar_job(rest, token, job_id, estado="running", iniciado_em=_agora_iso(),
                  tentativas=int(job.get("tentativas") or 0) + 1)

    nome_do_ator = _nome_de(rest, token, auth_user_id)
    usuario = _usuario({"id": usuario_id, "auth_user_id": auth_user_id,
                        "secretaria_id": secretaria_id, "nome": nome_do_ator})
    try:
        with sessao_da_requisicao(token, tenant_id, usuario=usuario):
            com_ciencia, visual = _flags()
            if not com_ciencia:
                return _falhar(rest, token, job_id, "EMISSION_UNAVAILABLE", SEM_CIENCIA)
            pesquisa, itens, referencias = _carregar(str(job["recurso_id"]), tenant_id)
            total = emissao.total_de_referencias(referencias)
            if (tipo, formato) not in {(t, f) for t, f, _ in opcoes(visual, total)}:
                return _falhar(rest, token, job_id, "INVALID_REPORT")
            emissao.conferir_cestas(pesquisa, itens, referencias)
            try:
                evento = ciencia.exigir(pesquisa, itens, referencias, ator=auth_user_id,
                                        repositorio=repo)
            except ciencia.CienciaNecessaria:
                return _falhar(rest, token, job_id, "CIENCIA_REQUIRED",
                               "Há alertas desta versão da cesta sem ciência registrada.")
            ciencia_doc = ciencia.para_documento(evento, nome_do_ator)
            marca_cache: dict = {}

            def gerar(f: str, t: str) -> tuple[bytes, str, str]:
                if emissao.precisa_de_marca(formato=f, tipo=t) and "m" not in marca_cache:
                    marca_cache["m"] = emissao.marca_resolvida()
                return emissao.renderizar(pesquisa, itens, referencias, formato=f, tipo=t,
                                          ciencia_doc=ciencia_doc, marca=marca_cache.get("m"))

            if tipo == "pacote":
                partes = emissao.partes_do_pacote(
                    visual=visual,
                    com_integral=com_integral and total <= emissao.LIMITE_DO_ANALITICO)
                arquivos = [(n, c) for c, n, _ in (gerar(f, t) for f, t in partes)]
                conteudo = emissao.zipar(arquivos)
                nome = relatorio.nome_do_arquivo(pesquisa, "pacote", "zip")
            else:
                conteudo, nome, _ = gerar(formato, tipo)
            artefato = artefatos.montar(nome, conteudo)
            expira = deposito.guardar(job_id, artefato)
            dados, registrado = emissao.registrar(
                pesquisa, itens, referencias,
                tipo=emissao.TIPO_NO_REGISTRO.get(tipo, tipo), formato=formato,
                conteudo=conteudo, nome=nome, ator=auth_user_id, ciencia_doc=ciencia_doc)
    except ErroApi as exc:
        if exc.status == 404:
            return _falhar(rest, token, job_id, "NOT_FOUND")
        raise
    except ErroDeRenderizacao as exc:
        # Cesta acima do teto ou PDF indisponível: o texto é do domínio,
        # escrito para o usuário.
        return _falhar(rest, token, job_id, "RENDER_REFUSED", str(exc))
    except artefatos.ArtefatoGrandeDemais:
        return _falhar(rest, token, job_id, "ARTIFACT_TOO_LARGE",
                       "O arquivo passou do limite de entrega. Gere a memória analítica (XLSX).")
    except repo.SemSessao:
        return "failed"          # token vencido: não há com que escrever
    except db.ErroBanco as exc:
        raise ErroTransitorio("banco") from exc
    except ConnectionError as exc:   # Redis
        raise ErroTransitorio("deposito") from exc
    atualizar_job(rest, token, job_id, estado="succeeded", concluido_em=_agora_iso(),
                  feitos=1, resultado={
                      "nome": artefato.nome, "mimetype": artefato.mimetype,
                      "tamanho": artefato.tamanho, "sha256": artefato.sha256,
                      "hash_decisorio": dados["hash_decisorio"], "registrado": registrado,
                      "expira_em": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(expira))})
    return "succeeded"


# ---------------------------------------------------------------------------
# Rotas
# ---------------------------------------------------------------------------
def rotas() -> APIRouter:
    r = APIRouter(tags=["precos"])

    def _rest(request: Request) -> ClienteRest:
        rest = getattr(request.app.state, "rest", None)
        if rest is None:
            raise ErroApi(503, "AUTH_UNAVAILABLE", "Autenticação indisponível neste ambiente")
        return rest

    def _pesquisa_visivel(rest: ClienteRest, eu: Identidade, pesquisa_id: uuid.UUID) -> dict:
        resposta = rest.requisitar(eu.token, "GET", TABELA_PESQUISAS, params={
            "select": "id,auth_user_id", "id": f"eq.{pesquisa_id}",
            "tenant_id": f"eq.{eu.tenant_id}", "limit": "1"})
        if resposta.status != 200 or not resposta.dados:
            raise ErroApi(404, "NOT_FOUND", "Recurso não encontrado")
        return resposta.dados[0]

    def _pode_escrever(eu: Identidade, pesquisa: dict) -> bool:
        # Espelha `pode_escrever_pesquisa_preco` (0021): admin ou dono.
        return eu.papel == "admin" or str(pesquisa.get("auth_user_id") or "") == eu.auth_user_id

    def _sessao(eu: Identidade):
        return sessao_da_requisicao(eu.token, eu.tenant_id, usuario=_usuario({
            "id": eu.usuario_id, "auth_user_id": eu.auth_user_id,
            "secretaria_id": eu.secretaria_id}))

    @r.get("/precos/pesquisas/{pesquisa_id}/emissao", response_model=PreparoDaEmissao,
           dependencies=[Depends(exigir_precos_habilitado)],
           responses={404: {"description": "Inexistente ou fora do seu acesso"},
                      503: {"description": "Banco ou flags indisponíveis"}})
    def preparar(pesquisa_id: uuid.UUID, request: Request,
                 eu: Identidade = Depends(exigir_identidade)) -> PreparoDaEmissao:
        dono = _pesquisa_visivel(_rest(request), eu, pesquisa_id)
        try:
            with _sessao(eu):
                com_ciencia, visual = _flags()
                pesquisa, itens, referencias = _carregar(str(pesquisa_id), eu.tenant_id)
                total = emissao.total_de_referencias(referencias)
                identificador = relatorio.identificador_da_versao(pesquisa, itens, referencias)
                try:
                    emissao.conferir_cestas(pesquisa, itens, referencias)
                    bloqueio = ""
                except ErroDeRenderizacao as exc:
                    bloqueio = str(exc)
                preparo = ciencia.preparar(
                    pesquisa, itens, referencias,
                    pareceres=ciencia.pareceres_do_jev(str(pesquisa_id), repo))
                registrada = (ciencia.localizar(preparo.pesquisa_id, preparo.assinatura,
                                                eu.auth_user_id, repo)
                              if preparo.requer_ciencia else None)
        except (repo.SemSessao, db.ErroBanco) as exc:
            raise _traduzir(exc) from None
        carga = (registrada or {}).get("payload") or {}
        return PreparoDaEmissao(
            disponivel=com_ciencia, motivo="" if com_ciencia else SEM_CIENCIA,
            identificador=identificador, bloqueio=bloqueio,
            requer_ciencia=preparo.requer_ciencia, assinatura=preparo.assinatura,
            alertas=[AlertaDePreco(numero=a.numero, descricao=a.descricao[:200],
                                   valor=valor_monetario(a.valor), origem=a.origem[:200],
                                   mensagem=a.mensagem[:300])
                     for a in preparo.alertas[:200]],
            pendencias=[PendenciaDeItem(numero=int(p.get("numero") or 0),
                                        descricao=str(p.get("descricao") or "")[:200],
                                        deficiencias=[str(d)[:300] for d in p.get("deficiencias") or []])
                        for p in preparo.pendencias[:500]],
            ciencia=(CienciaRegistrada(
                registrada_em=str(carga.get("registrada_em") or registrada.get("criado_em") or ""),
                assinatura=preparo.assinatura) if registrada else None),
            pode_registrar_ciencia=_pode_escrever(eu, dono),
            opcoes=[OpcaoDeRelatorio(tipo=t, formato=f, rotulo=n) for t, f, n in opcoes(visual, total)],
            total_referencias=total)

    @r.post("/precos/pesquisas/{pesquisa_id}/ciencia", status_code=201,
            response_model=CienciaRegistrada,
            dependencies=[Depends(exigir_precos_habilitado)],
            responses={403: {"description": "Só o dono da pesquisa ou o administrador"},
                       404: {"description": "Inexistente ou fora do seu acesso"},
                       409: {"description": "A cesta mudou desde o aviso (CIENCIA_DESATUALIZADA)"}})
    def registrar_ciencia(pesquisa_id: uuid.UUID, corpo: PedidoDeCiencia, request: Request,
                          eu: Identidade = Depends(exigir_identidade)) -> CienciaRegistrada:
        if not _ASSINATURA.fullmatch(corpo.assinatura):
            raise ErroApi(422, "VALIDATION_ERROR", "Assinatura inválida")
        dono = _pesquisa_visivel(_rest(request), eu, pesquisa_id)
        if not _pode_escrever(eu, dono):
            raise ErroApi(403, "FORBIDDEN", "Só quem criou a pesquisa (ou o administrador) "
                                            "pode registrar a ciência.")
        try:
            with _sessao(eu):
                com_ciencia, _ = _flags()
                if not com_ciencia:
                    raise ErroApi(409, "EMISSION_UNAVAILABLE", SEM_CIENCIA)
                pesquisa, itens, referencias = _carregar(str(pesquisa_id), eu.tenant_id)
                atual = ciencia.preparar(
                    pesquisa, itens, referencias,
                    pareceres=ciencia.pareceres_do_jev(str(pesquisa_id), repo))
                if atual.assinatura != corpo.assinatura:
                    # O cliente confirmou o que viu; a cesta mudou desde então.
                    raise ErroApi(409, "CIENCIA_DESATUALIZADA",
                                  "A cesta mudou desde o aviso. Confira os alertas atualizados.")
                if not atual.requer_ciencia:
                    return CienciaRegistrada(registrada_em="", assinatura=atual.assinatura)
                evento = ciencia.registrar(
                    pesquisa, atual, ator=eu.auth_user_id, repositorio=repo,
                    recarregar=lambda: _carregar(str(pesquisa_id), eu.tenant_id)[1:])
        except ciencia.CienciaDesatualizada:
            raise ErroApi(409, "CIENCIA_DESATUALIZADA",
                          "A cesta mudou desde o aviso. Confira os alertas atualizados.") from None
        except ciencia.ErroDeCiencia:
            raise ErroApi(503, "DATABASE_UNAVAILABLE",
                          "Não foi possível registrar a ciência agora. Tente de novo.") from None
        except (repo.SemSessao, db.ErroBanco) as exc:
            raise _traduzir(exc) from None
        carga = evento.get("payload") or {}
        return CienciaRegistrada(registrada_em=str(carga.get("registrada_em")
                                                   or evento.get("criado_em") or ""),
                                 assinatura=atual.assinatura)

    @r.post("/precos/pesquisas/{pesquisa_id}/relatorios", status_code=202, response_model=Job,
            dependencies=[Depends(exigir_precos_habilitado)],
            responses={200: {"model": Job, "description": "Repetição da mesma Idempotency-Key"},
                       404: {"description": "Inexistente ou fora do seu acesso"},
                       409: {"description": "Emissão indisponível nesta configuração"},
                       503: {"description": "Fila indisponível"}})
    def pedir_relatorio(pesquisa_id: uuid.UUID, request: Request, response: Response,
                        pedido: PedidoDeRelatorio = Body(...),
                        idempotency_key: str = Header(..., alias="Idempotency-Key"),
                        eu: Identidade = Depends(exigir_identidade)) -> Job:
        if not _CHAVE.fullmatch(idempotency_key):
            raise ErroApi(400, "INVALID_IDEMPOTENCY_KEY", "Idempotency-Key inválida")
        rest = _rest(request)
        _pesquisa_visivel(rest, eu, pesquisa_id)
        try:
            with _sessao(eu):
                com_ciencia, visual = _flags()
        except (repo.SemSessao, db.ErroBanco) as exc:
            raise _traduzir(exc) from None
        if not com_ciencia:
            raise ErroApi(409, "EMISSION_UNAVAILABLE", SEM_CIENCIA)
        # O limite do analítico integral depende das referências; o worker
        # confere. Aqui, só o vocabulário do gerador ativo.
        if (pedido.tipo, pedido.formato) not in {(t, f) for t, f, _ in opcoes(visual, 0)}:
            raise ErroApi(422, "VALIDATION_ERROR", "Relatório não oferecido nesta configuração")

        criado = rest.requisitar(eu.token, "POST", TABELA_JOBS, prefer="return=representation",
                                 corpo={"tenant_id": eu.tenant_id, "auth_user_id": eu.auth_user_id,
                                        "tipo": TIPO_DO_JOB, "recurso_id": str(pesquisa_id),
                                        "parametros": pedido.model_dump(), "total": 1,
                                        "idempotency_key": idempotency_key})
        if criado.status == 409 and criado.codigo_pg == "23505":
            existente = rest.requisitar(eu.token, "GET", TABELA_JOBS, params={
                "select": "*", "idempotency_key": f"eq.{idempotency_key}",
                "tenant_id": f"eq.{eu.tenant_id}", "limit": "1"})
            linha = (existente.dados or [None])[0] if existente.status == 200 else None
            if (not linha or str(linha.get("recurso_id")) != str(pesquisa_id)
                    or linha.get("tipo") != TIPO_DO_JOB
                    or (linha.get("parametros") or {}) != pedido.model_dump()):
                raise ErroApi(409, "IDEMPOTENCY_KEY_REUSED",
                              "Idempotency-Key já usada com outro conteúdo")
            response.status_code = 200
            response.headers["Idempotent-Replayed"] = "true"
            return job_do_banco(linha)
        if criado.status != 201 or not criado.dados:
            raise ErroApi(400, "BAD_REQUEST", "Não foi possível registrar o pedido")
        linha = criado.dados[0]

        fila: Fila | None = getattr(request.app.state, "fila", None)
        try:
            if fila is None:
                raise RuntimeError("sem fila")
            fila.enfileirar(job_id=str(linha["id"]), token=eu.token, tenant_id=eu.tenant_id,
                            auth_user_id=eu.auth_user_id, secretaria_id=eu.secretaria_id,
                            usuario_id=eu.usuario_id, tarefa="relatorio")
        except Exception:  # noqa: BLE001
            _log.warning("fila_indisponivel job=%s", linha["id"])
            atualizar_job(rest, eu.token, str(linha["id"]), estado="failed",
                          erro_codigo="QUEUE_UNAVAILABLE", concluido_em=_agora_iso())
            raise ErroApi(503, "QUEUE_UNAVAILABLE",
                          "Emissão indisponível no momento. Tente de novo em instantes.") from None
        response.headers["Location"] = f"/api/v1/jobs/{linha['id']}"
        return job_do_banco(linha)

    @r.get("/jobs/{job_id}/artefato",
           responses={200: {"description": "O arquivo gerado",
                            "content": {m: {} for m in artefatos.MIME_POR_EXTENSAO.values()}},
                      404: {"description": "Inexistente, de outra pessoa ou sem arquivo"},
                      410: {"description": "O arquivo expirou; gere de novo"}})
    def baixar(job_id: uuid.UUID, request: Request,
               eu: Identidade = Depends(exigir_identidade)) -> Response:
        # O RLS da 0031 é quem diz que o job é seu (dono + município).
        resposta = _rest(request).requisitar(eu.token, "GET", TABELA_JOBS, params={
            "select": "id,tipo,estado", "id": f"eq.{job_id}",
            "tenant_id": f"eq.{eu.tenant_id}", "limit": "1"})
        if resposta.status != 200 or not resposta.dados:
            raise ErroApi(404, "NOT_FOUND", "Recurso não encontrado")
        job = resposta.dados[0]
        if job.get("tipo") != TIPO_DO_JOB or job.get("estado") != "succeeded":
            raise ErroApi(404, "NOT_FOUND", "Recurso não encontrado")
        deposito: artefatos.Deposito | None = getattr(request.app.state, "deposito", None)
        if deposito is None:
            raise ErroApi(503, "STORAGE_UNAVAILABLE", "Arquivos indisponíveis no momento")
        try:
            artefato = deposito.ler(str(job_id))
        except Exception:  # noqa: BLE001 — Redis fora
            raise ErroApi(503, "STORAGE_UNAVAILABLE", "Arquivos indisponíveis no momento") from None
        if artefato is None:
            raise ErroApi(410, "ARTIFACT_EXPIRED", "O arquivo expirou. Gere o relatório de novo.")
        nome = urllib.parse.quote(artefato.nome, safe="")
        ascii_ = re.sub(r"[^A-Za-z0-9._-]", "_", artefato.nome)[:150] or "relatorio"
        return Response(content=artefato.conteudo, media_type=artefato.mimetype, headers={
            "Content-Disposition": f"attachment; filename=\"{ascii_}\"; filename*=UTF-8''{nome}",
            "Cache-Control": "private, no-store",
            "X-Content-Type-Options": "nosniff",
            "X-Artefato-SHA256": artefato.sha256})

    return r
