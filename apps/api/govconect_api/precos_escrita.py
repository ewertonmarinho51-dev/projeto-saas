"""
Pesquisa de preços: criar, importar a planilha, concluir e reabrir item (P04e).

Como as fatias anteriores, a regra NÃO mora aqui. Cada rota chama a mesma
função que o Streamlit chama:

    POST /precos/pesquisas                         cotacoes.criar_cotacao
    POST /precos/pesquisas/{id}/importacao         importacao.diagnosticar
                                                   + planejar (+ aplicar)
    POST /precos/pesquisas/{id}/itens/{i}/conclusao  cotacoes.concluir_item
    POST /precos/pesquisas/{id}/itens/{i}/reabertura cotacoes.reabrir_item

A cotação automática não precisa de rota nova: é a coleta do P04c com
`modo: "automatico"` (teto e triagem valem pela API desde a 0033).

**Importação em dois passos, o plano conferido pelo SERVIDOR.** O
primeiro envio (`confirmar=false`) diagnostica a planilha inteira e
devolve o plano (novo / atualizar / igual / refaz a busca) com o hash
dele. A confirmação reenvia o arquivo com `If-Match: "<hash>"`; o
servidor refaz diagnóstico e plano e só grava se der o MESMO plano. Se a
cotação mudou no meio (outra aba incluiu item), 409 e o usuário confere
de novo — o plano do cliente nunca é executado como veio.

**Quem escreve.** Dono da pesquisa ou admin (0021: `pode_escrever_
pesquisa_preco`); o RLS confere de novo. Criar é de qualquer usuário
autenticado do município (a pesquisa nasce dele).
"""

from __future__ import annotations

import hashlib
import json
import re
import uuid
from datetime import date

from fastapi import APIRouter, Body, Depends, Header, Query, Request, Response
from pydantic import BaseModel, ConfigDict, Field

from src import db
from src.precos import cotacoes, importacao
from src.precos import repositorio as repo
from src.precos.perfil import PERFIS
from src.streamlit_opcional import sessao_da_requisicao

from .cesta import _revisao
from .erros import ErroApi
from .precos import TABELA_ITENS, TABELA_PESQUISAS, exigir_precos_habilitado
from .seguranca import Identidade, exigir_identidade
from .supabase_rest import ClienteRest

_CHAVE = re.compile(r"^[A-Za-z0-9._:-]{8,128}$")
LIMITE_PLANILHA = 5 * 1024 * 1024
MIME_XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


# ---------------------------------------------------------------------------
# Contratos
# ---------------------------------------------------------------------------
class NovaPesquisa(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    nome: str = Field(min_length=1, max_length=200)
    objeto: str = Field(default="", max_length=2000)
    responsavel: str = Field(default="", max_length=200)
    local_referencia: str = Field(default="", max_length=200)
    data_base: date | None = None
    perfil_normativo: str = "lei_14133"
    processo_id: uuid.UUID | None = None
    uf: str | None = Field(default=None, min_length=2, max_length=2)


class PesquisaCriada(BaseModel):
    id: str
    nome: str
    estado: str


class ErroDaPlanilha(BaseModel):
    linha: int
    campo: str
    valor: str
    motivo: str


class AcaoDoPlano(BaseModel):
    numero: int
    tipo: str               # novo | atualizar | igual
    descricao: str
    unidade: str
    quantidade: str         # decimal canônico, nunca float
    codigo: str
    mudancas: list[str]
    refaz_busca: bool


class PlanoDeImportacao(BaseModel):
    pode_importar: bool
    erros: list[ErroDaPlanilha]
    linhas_em_branco: int
    resumo: dict[str, int]
    acoes: list[AcaoDoPlano]
    plano: str              # hash: o que a confirmação manda em If-Match
    gravado: bool


class Justificativa(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    justificativa: str = Field(default="", max_length=2000)


class Motivo(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    motivo: str = Field(min_length=1, max_length=1000)


class ItemDepois(BaseModel):
    id: str
    estado: str
    revisao: int


# ---------------------------------------------------------------------------
# Apoio
# ---------------------------------------------------------------------------
def _hash_do_plano(plano: list[importacao.Acao]) -> str:
    """O plano reduzido ao que muda o banco. Mesmo arquivo + mesma cotação
    = mesmo hash; qualquer item novo na cotação muda os números e o hash."""
    canonico = [(a.tipo, a.numero, a.item_id or "", a.linha.codigo, a.linha.descricao,
                 a.linha.unidade, format(a.linha.quantidade, "f"), a.linha.uf,
                 a.linha.lote, sorted(a.mudancas), a.refaz_busca) for a in plano]
    return hashlib.sha256(json.dumps(canonico, ensure_ascii=False).encode()).hexdigest()


def _traduzir(exc: Exception) -> ErroApi:
    if isinstance(exc, repo.ConflitoDeVersao):
        return ErroApi(409, "VERSION_CONFLICT",
                       "O item mudou desde a sua leitura. Recarregue e refaça.")
    if isinstance(exc, cotacoes.CotacaoImutavel):
        return ErroApi(409, "IMMUTABLE", "Cotação aplicada ou arquivada: crie uma revisão nova.")
    if isinstance(exc, cotacoes.ErroCotacao):
        return ErroApi(422, "DOMAIN_RULE", str(exc))
    if isinstance(exc, repo.SemSessao):
        return ErroApi(401, "UNAUTHENTICATED", "Sessão ausente, expirada ou inválida",
                       {"WWW-Authenticate": "Bearer"})
    return ErroApi(503, "DATABASE_UNAVAILABLE", "Banco de dados indisponível")


_TRADUZIVEIS = (repo.ConflitoDeVersao, cotacoes.ErroCotacao, db.ErroBanco)


# ---------------------------------------------------------------------------
# Rotas
# ---------------------------------------------------------------------------
def rotas() -> APIRouter:
    r = APIRouter(prefix="/precos", tags=["precos"],
                  dependencies=[Depends(exigir_precos_habilitado)])

    def _rest(request: Request) -> ClienteRest:
        rest = getattr(request.app.state, "rest", None)
        if rest is None:
            raise ErroApi(503, "AUTH_UNAVAILABLE", "Autenticação indisponível neste ambiente")
        return rest

    def _ctx(eu: Identidade) -> cotacoes.Contexto:
        return cotacoes.Contexto(auth_user_id=eu.auth_user_id, secretaria_id=eu.secretaria_id)

    def _exigir_dono(rest: ClienteRest, eu: Identidade, pesquisa_id: uuid.UUID) -> dict:
        resposta = rest.requisitar(eu.token, "GET", TABELA_PESQUISAS, params={
            "select": "id,auth_user_id,estado", "id": f"eq.{pesquisa_id}",
            "tenant_id": f"eq.{eu.tenant_id}", "limit": "1"})
        if resposta.status != 200 or not resposta.dados:
            raise ErroApi(404, "NOT_FOUND", "Recurso não encontrado")
        linha = resposta.dados[0]
        # Espelha `pode_escrever_pesquisa_preco` (0021): admin ou dono.
        if eu.papel != "admin" and str(linha.get("auth_user_id") or "") != eu.auth_user_id:
            raise ErroApi(403, "FORBIDDEN", "Só quem criou a pesquisa (ou o administrador) pode alterá-la.")
        return linha

    def _item_da_pesquisa(rest: ClienteRest, eu: Identidade, pesquisa_id, item_id) -> dict:
        resposta = rest.requisitar(eu.token, "GET", TABELA_ITENS, params={
            "select": "id", "id": f"eq.{item_id}", "pesquisa_id": f"eq.{pesquisa_id}",
            "tenant_id": f"eq.{eu.tenant_id}", "removido_em": "is.null", "limit": "1"})
        if resposta.status != 200 or not resposta.dados:
            raise ErroApi(404, "NOT_FOUND", "Recurso não encontrado")
        return resposta.dados[0]

    # -- criar ------------------------------------------------------------
    @r.post("/pesquisas", status_code=201, response_model=PesquisaCriada,
            responses={200: {"model": PesquisaCriada, "description": "Repetição da mesma Idempotency-Key"},
                       404: {"description": "Processo inexistente ou fora do seu acesso"},
                       422: {"description": "Regra do domínio recusou"}})
    def criar(pedido: NovaPesquisa, request: Request, response: Response,
              idempotency_key: str = Header(..., alias="Idempotency-Key"),
              eu: Identidade = Depends(exigir_identidade)) -> PesquisaCriada:
        if not _CHAVE.fullmatch(idempotency_key):
            raise ErroApi(400, "INVALID_IDEMPOTENCY_KEY", "Idempotency-Key inválida")
        if pedido.perfil_normativo not in PERFIS:
            raise ErroApi(422, "VALIDATION_ERROR", "Perfil normativo desconhecido")
        if pedido.processo_id is not None:
            # Vincular só a processo que o usuário VÊ, no município dele.
            visto = _rest(request).requisitar(eu.token, "GET", "processos", params={
                "select": "id", "id": f"eq.{pedido.processo_id}",
                "tenant_id": f"eq.{eu.tenant_id}", "limit": "1"})
            if visto.status != 200 or not visto.dados:
                raise ErroApi(404, "NOT_FOUND", "Processo não encontrado")
        # A chave da API é do USUÁRIO; no banco ela é única por pesquisa e
        # serve também a outra origem (Streamlit). O prefixo separa.
        chave = f"api:{eu.auth_user_id}:{idempotency_key}"
        try:
            with sessao_da_requisicao(eu.token, eu.tenant_id):
                existente = repo.obter_por_chave(chave)
                if existente:
                    response.status_code = 200
                    response.headers["Idempotent-Replayed"] = "true"
                    linha = existente
                else:
                    dados = pedido.model_dump(exclude_none=True)
                    if pedido.processo_id is not None:
                        dados["processo_id"] = str(pedido.processo_id)
                    linha = cotacoes.criar_cotacao(_ctx(eu), dados, idempotency_key=chave)
        except _TRADUZIVEIS as exc:
            raise _traduzir(exc) from None
        response.headers["Location"] = f"/api/v1/precos/pesquisas/{linha['id']}"
        return PesquisaCriada(id=str(linha["id"]), nome=str(linha.get("nome") or ""),
                              estado=str(linha.get("estado") or ""))

    # -- importar a planilha ------------------------------------------------
    @r.post("/pesquisas/{pesquisa_id}/importacao", response_model=PlanoDeImportacao,
            openapi_extra={"requestBody": {"required": True, "content": {
                MIME_XLSX: {"schema": {"type": "string", "format": "binary"}}}}},
            responses={403: {"description": "Só o dono ou o administrador"},
                       409: {"description": "O plano mudou desde a conferência (PLANO_DESATUALIZADO)"},
                       413: {"description": "Planilha acima do limite"},
                       415: {"description": "Não é XLSX"},
                       422: {"description": "Planilha com erros (nada gravado)"}})
    async def importar(pesquisa_id: uuid.UUID, request: Request,
                       confirmar: bool = Query(False),
                       if_match: str | None = Header(None, alias="If-Match"),
                       eu: Identidade = Depends(exigir_identidade)) -> PlanoDeImportacao:
        tipo = (request.headers.get("content-type") or "").split(";")[0].strip()
        if tipo != MIME_XLSX:
            raise ErroApi(415, "UNSUPPORTED_MEDIA_TYPE", "Envie a planilha em XLSX")
        tamanho = int(request.headers.get("content-length") or 0)
        if tamanho > LIMITE_PLANILHA:
            raise ErroApi(413, "PAYLOAD_TOO_LARGE", "A planilha passa de 5 MB")
        conteudo = await request.body()
        if len(conteudo) > LIMITE_PLANILHA:
            raise ErroApi(413, "PAYLOAD_TOO_LARGE", "A planilha passa de 5 MB")
        if not conteudo.startswith(b"PK"):
            raise ErroApi(415, "UNSUPPORTED_MEDIA_TYPE", "O arquivo não é um XLSX válido")
        _exigir_dono(_rest(request), eu, pesquisa_id)
        esperado = (if_match or "").strip().removeprefix("W/").strip('"')
        if confirmar and not re.fullmatch(r"[0-9a-f]{64}", esperado):
            raise ErroApi(428, "PRECONDITION_REQUIRED",
                          "Confirme com If-Match: o plano que você conferiu")
        try:
            diag = importacao.diagnosticar(conteudo)
        except Exception:  # noqa: BLE001 — openpyxl recusa arquivo malformado
            raise ErroApi(415, "UNSUPPORTED_MEDIA_TYPE", "O arquivo não é um XLSX legível") from None
        gravado = False
        try:
            with sessao_da_requisicao(eu.token, eu.tenant_id):
                cotacoes._exigir_editavel(repo.obter_pesquisa(str(pesquisa_id)))  # noqa: SLF001
                plano = importacao.planejar(diag, cotacoes.ativos(repo.listar_itens(str(pesquisa_id))))
                hash_atual = _hash_do_plano(plano)
                if confirmar:
                    if not diag.pode_importar:
                        raise ErroApi(422, "SPREADSHEET_ERRORS",
                                      "A planilha tem erros; nada foi gravado.")
                    mudam = [a for a in plano if a.tipo != "igual"]
                    if hash_atual != esperado and mudam:
                        raise ErroApi(409, "PLANO_DESATUALIZADO",
                                      "A cotação mudou desde a conferência. Confira o plano de novo.")
                    if mudam:
                        importacao.aplicar(str(pesquisa_id), plano, repo)
                        repo.registrar_evento(
                            str(pesquisa_id), "item_editado", ator=eu.auth_user_id,
                            descricao=f"planilha importada: {importacao.resumo_do_plano(plano)}",
                            idempotency_key=f"importacao:{pesquisa_id}:{hash_atual}")
                        cotacoes.sincronizar_estado(str(pesquisa_id))
                        gravado = True
        except _TRADUZIVEIS as exc:
            raise _traduzir(exc) from None
        return PlanoDeImportacao(
            pode_importar=diag.pode_importar,
            erros=[ErroDaPlanilha(linha=e.linha, campo=e.campo[:60], valor=str(e.valor)[:200],
                                  motivo=e.motivo[:300]) for e in diag.erros[:300]],
            linhas_em_branco=diag.em_branco,
            resumo=importacao.resumo_do_plano(plano),
            acoes=[AcaoDoPlano(numero=a.numero, tipo=a.tipo, descricao=a.linha.descricao[:300],
                               unidade=a.linha.unidade, quantidade=format(a.linha.quantidade, "f"),
                               codigo=a.linha.codigo or "", mudancas=list(a.mudancas),
                               refaz_busca=a.refaz_busca) for a in plano[:1000]],
            plano=hash_atual, gravado=gravado)

    # -- concluir e reabrir item -------------------------------------------
    def _depois(item_id: str) -> ItemDepois:
        linha = repo.obter_item(item_id) or {}
        return ItemDepois(id=item_id, estado=str(linha.get("estado") or ""),
                          revisao=int(linha.get("revisao") or 0))

    @r.post("/pesquisas/{pesquisa_id}/itens/{item_id}/conclusao", response_model=ItemDepois,
            responses={403: {"description": "Só o dono ou o administrador"},
                       404: {"description": "Inexistente ou fora do seu acesso"},
                       409: {"description": "Revisão desatualizada ou cotação imutável"},
                       422: {"description": "Regra do domínio recusou (ex.: falta justificativa)"},
                       428: {"description": "If-Match ausente"}})
    def concluir(pesquisa_id: uuid.UUID, item_id: uuid.UUID, request: Request,
                 corpo: Justificativa = Body(default_factory=Justificativa),
                 if_match: str | None = Header(None, alias="If-Match"),
                 eu: Identidade = Depends(exigir_identidade)) -> ItemDepois:
        revisao = _revisao(if_match)
        rest = _rest(request)
        _exigir_dono(rest, eu, pesquisa_id)
        _item_da_pesquisa(rest, eu, pesquisa_id, item_id)
        try:
            with sessao_da_requisicao(eu.token, eu.tenant_id):
                cotacoes.concluir_item(_ctx(eu), str(pesquisa_id), str(item_id),
                                       justificativa=corpo.justificativa,
                                       revisao_esperada=revisao)
                return _depois(str(item_id))
        except _TRADUZIVEIS as exc:
            raise _traduzir(exc) from None

    @r.post("/pesquisas/{pesquisa_id}/itens/{item_id}/reabertura", response_model=ItemDepois,
            responses={403: {"description": "Só o dono ou o administrador"},
                       404: {"description": "Inexistente ou fora do seu acesso"},
                       409: {"description": "Cotação imutável"},
                       422: {"description": "Regra do domínio recusou (ex.: motivo curto)"}})
    def reabrir(pesquisa_id: uuid.UUID, item_id: uuid.UUID, corpo: Motivo, request: Request,
                eu: Identidade = Depends(exigir_identidade)) -> ItemDepois:
        rest = _rest(request)
        _exigir_dono(rest, eu, pesquisa_id)
        _item_da_pesquisa(rest, eu, pesquisa_id, item_id)
        try:
            with sessao_da_requisicao(eu.token, eu.tenant_id):
                cotacoes.reabrir_item(_ctx(eu), str(pesquisa_id), str(item_id), corpo.motivo)
                return _depois(str(item_id))
        except _TRADUZIVEIS as exc:
            raise _traduzir(exc) from None

    return r
