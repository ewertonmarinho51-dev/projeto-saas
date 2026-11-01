"""
`/api/v1/processos` — listar, criar, consultar e editar.

Toda leitura e escrita vai ao PostgREST com o JWT de quem pediu, e quem
decide o que essa pessoa vê é o RLS da 0020 (`pode_ler_processo`: mesmo
tenant e, fora o admin, mesma secretaria). O `eq.tenant_id` que aparece
aqui é defesa em profundidade, não a contenção.

Status, etapa e progresso vêm de `src/processos.py`, a mesma função pura
que o painel do Streamlit usa — derivar de novo aqui criaria uma segunda
verdade sobre o andamento do processo.

Fora do escopo deste PR, de propósito: `dados` e `documentos` completos
(entram com o adapter do editor, P05) e exclusão (a 0020 não dá DELETE
ao `authenticated`).
"""

from __future__ import annotations

import base64
import json
import logging
import re
import uuid
from datetime import datetime

from fastapi import APIRouter, Depends, Header, Query, Request, Response
from pydantic import BaseModel, ConfigDict, Field, field_validator

from src import processos as dominio

from .erros import ErroApi
from .seguranca import Identidade, exigir_identidade
from .supabase_rest import ClienteRest, RespostaRest

_log = logging.getLogger("govconect_api")

_COLUNAS = ("id,nome,orgao,objeto,etapa,dados,documentos,aprovados,"
            "criado_em,atualizado_em,secretaria_id,auth_user_id,idempotency_key")
_CHAVE_IDEMPOTENCIA = re.compile(r"^[A-Za-z0-9._:-]{8,128}$")


# ---------------------------------------------------------------------------
# Contratos
# ---------------------------------------------------------------------------
class _Entrada(BaseModel):
    # `extra="forbid"`: corpo com `tenant_id`, `auth_user_id`, `papel` ou
    # qualquer outro campo que não seja conteúdo é RECUSADO (422), não
    # ignorado em silêncio. Ignorar esconderia a tentativa.
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class NovoProcesso(_Entrada):
    nome: str = Field(default="", max_length=120)
    orgao: str = Field(min_length=1, max_length=200)
    objeto: str = Field(min_length=1, max_length=2000)


class EdicaoDeProcesso(_Entrada):
    nome: str | None = Field(default=None, max_length=120)
    orgao: str | None = Field(default=None, min_length=1, max_length=200)
    objeto: str | None = Field(default=None, min_length=1, max_length=2000)

    @field_validator("orgao", "objeto")
    @classmethod
    def _nao_vazio(cls, valor):
        if valor is not None and not valor:
            raise ValueError("vazio")
        return valor


class Progresso(BaseModel):
    feitos: int
    total: int


class Processo(BaseModel):
    id: str
    nome: str
    nome_exibido: str
    orgao: str
    objeto: str
    status: str
    etapa: str
    progresso: Progresso
    criado_em: str
    atualizado_em: str
    versao: str


class PaginaDeProcessos(BaseModel):
    itens: list[Processo]
    proximo_cursor: str | None


# ---------------------------------------------------------------------------
# Tradução linha → contrato
# ---------------------------------------------------------------------------
def _para_contrato(linha: dict) -> Processo:
    resumo = dominio.resumo(linha)
    feitos, total = resumo["progresso"]
    return Processo(
        id=str(linha["id"]), nome=resumo["nome_proprio"],
        nome_exibido=resumo["nome"], orgao=resumo["orgao"],
        objeto=resumo["objeto"], status=resumo["status"],
        etapa=resumo["etapa"], progresso=Progresso(feitos=feitos, total=total),
        criado_em=str(linha.get("criado_em") or ""),
        atualizado_em=str(linha.get("atualizado_em") or ""),
        versao=str(linha.get("atualizado_em") or ""))


def _com_aprovacao_nativa(rest: ClienteRest, token: str, linhas: list[dict]) -> list[dict]:
    """Soma às aprovações as do editor nativo, que moram em `documentos_editor`.

    O dono documental não toca em `processos.aprovados`, e sem isto a lista
    diria "0 de 5" para um processo com tudo aprovado. Falhar a leitura só
    deixa o progresso como estava: é informação, não decisão."""
    if not linhas:
        return linhas
    ids = ",".join(str(l["id"]) for l in linhas)
    try:
        r = rest.requisitar(token, "GET", "documentos_editor", params={
            "select": "processo_id,tipo", "processo_id": f"in.({ids})",
            "status": "in.(aprovado,emitido)", "limit": "1000"})
    except ErroApi as exc:
        # Esta consulta apenas enriquece o progresso legado. Se o banco não
        # conseguiu ler as cabeças nativas, preserve o resumo já autorizado;
        # erros de sessão ou permissão continuam chegando ao cliente.
        if exc.status != 503:
            raise
        return linhas
    if r.status != 200 or not r.dados:
        return linhas
    por_processo: dict[str, set[str]] = {}
    for cabeca in r.dados:
        por_processo.setdefault(str(cabeca.get("processo_id")), set()).add(str(cabeca.get("tipo")))
    return [{**l, "aprovados": sorted(set(l.get("aprovados") or []) | por_processo.get(str(l["id"]), set()))}
            for l in linhas]


def _etag(linha: dict) -> str:
    return f'"{linha.get("atualizado_em") or ""}"'


def _sem_aspas(valor: str) -> str:
    valor = valor.strip()
    if valor.startswith("W/"):
        valor = valor[2:]
    return valor.strip('"')


def _cursor(linha: dict) -> str:
    bruto = json.dumps([linha["atualizado_em"], str(linha["id"])])
    return base64.urlsafe_b64encode(bruto.encode()).decode().rstrip("=")


def _ler_cursor(cursor: str) -> tuple[str, str]:
    try:
        bruto = base64.urlsafe_b64decode(cursor + "=" * (-len(cursor) % 4))
        momento, ident = json.loads(bruto)
        datetime.fromisoformat(momento)
        return momento, str(uuid.UUID(ident))
    except Exception:  # noqa: BLE001 — qualquer defeito é cursor inválido
        raise ErroApi(400, "INVALID_CURSOR", "Cursor inválido") from None


# Só letra (com acento), dígito e o que aparece em número de processo e
# de lei. O resto — vírgula, parênteses, aspas, barra invertida, `*`, `%`,
# `_` — tem sentido na sintaxe do PostgREST ou do LIKE e vira espaço: a
# busca nunca injeta filtro nem curinga.
_FORA_DA_BUSCA = re.compile(r"[^\w./-]|_", re.UNICODE)
_CAMPOS_DA_BUSCA = ("nome", "orgao", "objeto")


def _filtro_de_busca(q: str | None) -> str | None:
    """`and=(or(nome.ilike."*p*",...),or(...))`: cada palavra em algum campo."""
    palavras = [p for p in _FORA_DA_BUSCA.sub(" ", q or "").split() if p][:5]
    if not palavras:
        return None
    grupos = (",".join(f'{c}.ilike."*{p[:40]}*"' for c in _CAMPOS_DA_BUSCA)
              for p in palavras)
    return "(" + ",".join(f"or({g})" for g in grupos) + ")"


def _falha(resposta: RespostaRest) -> ErroApi:
    codigo = resposta.codigo_pg
    if codigo == "42501" or resposta.status == 403:
        return ErroApi(403, "FORBIDDEN", "Acesso negado")
    _log.warning("postgrest_recusou status=%s codigo=%s", resposta.status, codigo)
    return ErroApi(400, "BAD_REQUEST", "Requisição inválida")


# ---------------------------------------------------------------------------
# Rotas
# ---------------------------------------------------------------------------
def rotas() -> APIRouter:
    r = APIRouter(prefix="/processos", tags=["processos"])

    def _rest(request: Request) -> ClienteRest:
        rest = getattr(request.app.state, "rest", None)
        if rest is None:
            raise ErroApi(503, "AUTH_UNAVAILABLE",
                          "Autenticação indisponível neste ambiente")
        return rest

    def _obter(rest: ClienteRest, eu: Identidade, processo_id: str) -> dict | None:
        resposta = rest.requisitar(eu.token, "GET", "processos", params={
            "select": _COLUNAS, "id": f"eq.{processo_id}",
            "tenant_id": f"eq.{eu.tenant_id}", "limit": "1"})
        if resposta.status != 200:
            raise _falha(resposta)
        return resposta.dados[0] if resposta.dados else None

    @r.get("", response_model=PaginaDeProcessos)
    def listar(request: Request,
               limit: int = Query(20, ge=1, le=100),
               cursor: str | None = Query(None, max_length=512),
               q: str | None = Query(None, max_length=100, description=(
                   "Busca no nome, no órgão e no objeto, feita pelo banco sobre "
                   "TODOS os processos visíveis (não só a página). Cada palavra "
                   "precisa aparecer em algum dos três campos.")),
               eu: Identidade = Depends(exigir_identidade)) -> PaginaDeProcessos:
        params: list[tuple[str, str]] = [
            ("select", _COLUNAS), ("tenant_id", f"eq.{eu.tenant_id}"),
            ("order", "atualizado_em.desc,id.desc"), ("limit", str(limit + 1))]
        busca = _filtro_de_busca(q)
        if busca:
            params.append(("and", busca))
        if cursor:
            momento, ident = _ler_cursor(cursor)
            # Cursor por (atualizado_em, id), não OFFSET: página estável
            # enquanto outros salvam, e custo constante no índice.
            params.append(("or", f'(atualizado_em.lt."{momento}",'
                                  f'and(atualizado_em.eq."{momento}",id.lt.{ident}))'))
        resposta = _rest(request).requisitar(eu.token, "GET", "processos",
                                             params=params)
        if resposta.status != 200:
            raise _falha(resposta)
        linhas = resposta.dados or []
        proximo = _cursor(linhas[limit - 1]) if len(linhas) > limit else None
        return PaginaDeProcessos(
            itens=[_para_contrato(l) for l in _com_aprovacao_nativa(_rest(request), eu.token, linhas[:limit])],
            proximo_cursor=proximo)

    @r.post("", status_code=201, response_model=Processo,
            responses={200: {"model": Processo,
                             "description": "Repetição da mesma Idempotency-Key"},
                       409: {"description": "Idempotency-Key já usada com outro conteúdo"}})
    def criar(corpo: NovoProcesso, request: Request, response: Response,
              idempotency_key: str = Header(..., alias="Idempotency-Key"),
              eu: Identidade = Depends(exigir_identidade)) -> Processo:
        if not _CHAVE_IDEMPOTENCIA.fullmatch(idempotency_key):
            raise ErroApi(400, "INVALID_IDEMPOTENCY_KEY",
                          "Idempotency-Key inválida (8–128 caracteres seguros)")
        rest = _rest(request)
        registro = {
            "nome": corpo.nome, "orgao": corpo.orgao, "objeto": corpo.objeto,
            "etapa": 0, "dados": {"orgao": corpo.orgao, "objeto": corpo.objeto},
            "documentos": {}, "aprovados": [],
            # Tudo abaixo vem da IDENTIDADE verificada, nunca do corpo.
            "tenant_id": eu.tenant_id, "auth_user_id": eu.auth_user_id,
            "secretaria_id": eu.secretaria_id,
            "idempotency_key": idempotency_key,
        }
        if eu.usuario_id:
            registro["usuario_id"] = eu.usuario_id
        resposta = rest.requisitar(eu.token, "POST", "processos",
                                   params={"select": _COLUNAS}, corpo=registro,
                                   prefer="return=representation")
        if resposta.status == 201 and resposta.dados:
            linha = resposta.dados[0]
        elif resposta.status == 409 and resposta.codigo_pg == "23505":
            linha = _repeticao(rest, eu, idempotency_key, corpo)
            response.status_code = 200
            response.headers["Idempotent-Replayed"] = "true"
        else:
            raise _falha(resposta)
        response.headers["ETag"] = _etag(linha)
        response.headers["Location"] = f"/api/v1/processos/{linha['id']}"
        return _para_contrato(linha)

    def _repeticao(rest: ClienteRest, eu: Identidade, chave: str,
                   corpo: NovoProcesso) -> dict:
        resposta = rest.requisitar(eu.token, "GET", "processos", params={
            "select": _COLUNAS, "tenant_id": f"eq.{eu.tenant_id}",
            "idempotency_key": f"eq.{chave}", "limit": "1"})
        linha = (resposta.dados or [None])[0] if resposta.status == 200 else None
        # A chave é única por município. Se quem a usou foi outra pessoa,
        # ou o conteúdo mudou, isto NÃO é repetição — é colisão, e devolver
        # o processo do outro seria vazamento dentro do próprio tenant.
        if (linha is None or linha.get("auth_user_id") != eu.auth_user_id
                or (linha.get("orgao"), linha.get("objeto"), linha.get("nome") or "")
                != (corpo.orgao, corpo.objeto, corpo.nome)):
            raise ErroApi(409, "IDEMPOTENCY_KEY_REUSED",
                          "Idempotency-Key já usada com outro conteúdo")
        return linha

    @r.get("/{processo_id}", response_model=Processo,
           responses={404: {"description": "Inexistente ou fora do seu acesso"}})
    def consultar(processo_id: uuid.UUID, request: Request, response: Response,
                  eu: Identidade = Depends(exigir_identidade)) -> Processo:
        linha = _obter(_rest(request), eu, str(processo_id))
        if linha is None:
            # 404 também para o processo de OUTRO município: 403 confirmaria
            # que o id existe, e o id vira oráculo.
            raise ErroApi(404, "NOT_FOUND", "Recurso não encontrado")
        response.headers["ETag"] = _etag(linha)
        return _para_contrato(_com_aprovacao_nativa(_rest(request), eu.token, [linha])[0])

    @r.patch("/{processo_id}", response_model=Processo,
             responses={404: {"description": "Inexistente ou fora do seu acesso"},
                        409: {"description": "Versão desatualizada"},
                        428: {"description": "If-Match ausente"}})
    def editar(processo_id: uuid.UUID, corpo: EdicaoDeProcesso,
               request: Request, response: Response,
               if_match: str | None = Header(None, alias="If-Match"),
               eu: Identidade = Depends(exigir_identidade)) -> Processo:
        if not if_match:
            raise ErroApi(428, "PRECONDITION_REQUIRED",
                          "If-Match obrigatório: envie a versão que você leu")
        mudancas = corpo.model_dump(exclude_none=True)
        if not mudancas:
            raise ErroApi(400, "BAD_REQUEST", "Nada para alterar")
        rest = _rest(request)
        atual = _obter(rest, eu, str(processo_id))
        if atual is None:
            raise ErroApi(404, "NOT_FOUND", "Recurso não encontrado")
        versao = _sem_aspas(if_match)
        if versao != str(atual.get("atualizado_em")):
            raise ErroApi(409, "VERSION_CONFLICT",
                          "O processo mudou desde a sua leitura")
        # Espelha `processos_edita`: lê quem é da secretaria, edita o dono
        # ou o admin. O RLS continua sendo quem garante; isto só devolve o
        # código certo em vez de um "0 linhas" ambíguo.
        if eu.papel != "admin" and atual.get("auth_user_id") != eu.auth_user_id:
            raise ErroApi(403, "FORBIDDEN", "Acesso negado")

        registro = dict(mudancas)
        # `orgao`/`objeto` vivem também em `dados`, de onde o Streamlit os
        # relê ao salvar. Atualizar só a coluna faria o próximo salvamento
        # do wizard desfazer esta edição.
        dados = dict(atual.get("dados") or {})
        for campo in ("orgao", "objeto"):
            if campo in mudancas:
                dados[campo] = mudancas[campo]
        registro["dados"] = dados

        resposta = rest.requisitar(eu.token, "PATCH", "processos", params={
            "select": _COLUNAS, "id": f"eq.{processo_id}",
            "tenant_id": f"eq.{eu.tenant_id}",
            # A trava otimista É este filtro: o gatilho da 0001 troca
            # `atualizado_em` a cada update, então dois PATCH com a mesma
            # versão não casam os dois.
            "atualizado_em": f"eq.{versao}"},
            corpo=registro, prefer="return=representation")
        if resposta.status != 200:
            raise _falha(resposta)
        if not resposta.dados:
            if _obter(rest, eu, str(processo_id)) is None:
                raise ErroApi(404, "NOT_FOUND", "Recurso não encontrado")
            raise ErroApi(409, "VERSION_CONFLICT",
                          "O processo mudou desde a sua leitura")
        linha = resposta.dados[0]
        response.headers["ETag"] = _etag(linha)
        return _para_contrato(linha)

    return r
