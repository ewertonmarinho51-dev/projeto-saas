"""
`/api/v1/precos` — leitura das pesquisas de preços (P04a).

Esta fatia só LÊ o que o Streamlit já grava nas tabelas da 0021. Coleta,
cesta, decisões e emissão entram nas fatias seguintes; aqui o que se
estabelece é o contrato de dinheiro e de evidência que elas vão herdar:

* **Dinheiro e quantidade são string decimal**, nunca número JSON. O
  banco guarda `numeric(18,4)`; o cliente PostgREST lê como `Decimal`
  (`decimal=True`) e a resposta leva `valor` canônico ("1234.5600") e
  `exibicao` ("R$ 1.234,56"), esta pela MESMA função do relatório
  (`estatistica.brl`, ROUND_HALF_UP no centavo). O navegador não soma nem
  arredonda nada.
* **Link de fonte só se verificável**: `links.resolver`, a mesma regra do
  PDF — https e host oficial (PNCP, Compras.gov). O `bruto` da coleta não
  sai da API; sai o link que se pode conferir e a identificação oficial.
* **RLS decide o que se vê** (0021: `pesquisas_preco_le` etc.), com o
  token do usuário. O `eq.tenant_id` é defesa em profundidade.

Atrás de `PRICE_RESEARCH_ENABLED`, desligada por padrão.
"""

from __future__ import annotations

import base64
import json
import uuid
from datetime import datetime
from decimal import Decimal

from fastapi import APIRouter, Depends, Query, Request
from pydantic import BaseModel

from src.precos import estatistica, links

from .erros import ErroApi
from .seguranca import Identidade, exigir_identidade
from .supabase_rest import ClienteRest, RespostaRest

TABELA_PESQUISAS = "pesquisas_preco"
TABELA_ITENS = "pesquisa_preco_itens"
TABELA_REFERENCIAS = "pesquisa_preco_referencias"

_COLUNAS_PESQUISA = ("id,nome,objeto,estado,valor_global,data_base,responsavel,"
                     "local_referencia,processo_id,versao,criado_em,atualizado_em")
_COLUNAS_ITEM = ("id,numero,codigo,tipo_catalogo,descricao,unidade,quantidade,"
                 "estado,metodo,preco_estimado,preco_total,justificativa,"
                 "lote,uf,revisao")
_COLUNAS_REFERENCIA = (
    "id,fonte_id,fonte_nome,fonte_tipo,id_externo,referencia_externa,"
    "descricao_original,unidade_original,valor_unitario_original,"
    "unidade_normalizada,valor_unitario_normalizado,natureza_valor,orgao,uf,"
    "municipio,fornecedor,data_compra,data_resultado,coletado_em,status,"
    "motivos,bruto")
LIMITE_ITENS = 2000          # a planilha real tem 210; folga sem ser infinita
LIMITE_REFERENCIAS = 500


# ---------------------------------------------------------------------------
# Contratos
# ---------------------------------------------------------------------------
class Valor(BaseModel):
    """Dinheiro ou quantidade exatos. `valor` é o canônico, para máquina;
    `exibicao` é o que se mostra, já arredondado pela regra do domínio."""

    valor: str
    exibicao: str


class ResumoPesquisa(BaseModel):
    id: str
    nome: str
    objeto: str
    estado: str
    valor_global: Valor | None
    atualizado_em: str


class Item(BaseModel):
    id: str
    numero: int
    codigo: str | None
    tipo_catalogo: str | None
    descricao: str
    unidade: str
    quantidade: Valor | None
    estado: str
    metodo: str | None
    preco_estimado: Valor | None
    preco_total: Valor | None
    justificativa: str
    lote: str | None
    uf: str | None
    # Controle otimista do item (0029); a fatia de escrita o exige de volta.
    revisao: int


class Pesquisa(ResumoPesquisa):
    data_base: str | None
    responsavel: str
    local_referencia: str
    processo_id: str | None
    versao: int
    criado_em: str
    itens: list[Item]


class Referencia(BaseModel):
    id: str
    fonte: str
    fonte_tipo: str
    natureza_valor: str
    status: str
    descricao_original: str
    unidade_original: str | None
    valor_unitario_original: Valor | None
    unidade_normalizada: str | None
    valor_unitario_normalizado: Valor | None
    orgao: str | None
    uf: str | None
    municipio: str | None
    fornecedor: str | None
    data_compra: str | None
    data_resultado: str | None
    coletado_em: str
    motivos: list[str]
    link_contratacao: str | None
    rotulo_contratacao: str
    link_fonte: str | None
    identificacao: str


class PaginaDePesquisas(BaseModel):
    itens: list[ResumoPesquisa]
    proximo_cursor: str | None


# ---------------------------------------------------------------------------
# Tradução
# ---------------------------------------------------------------------------
def _decimal(valor) -> Decimal | None:
    if valor is None or valor == "":
        return None
    if isinstance(valor, float):
        # Não deveria chegar aqui (o cliente lê com decimal=True). Se
        # chegar, é defeito de quem chamou: falha alto em vez de arredondar.
        raise TypeError("dinheiro chegou como float")
    return Decimal(str(valor))


def valor_monetario(valor) -> Valor | None:
    d = _decimal(valor)
    if d is None:
        return None
    return Valor(valor=format(d, "f"), exibicao=estatistica.brl(d))


def valor_quantidade(valor) -> Valor | None:
    """Quantidade sem arredondar: "1.500" para 1500.0000, "2,5" para 2.5000."""
    d = _decimal(valor)
    if d is None:
        return None
    sinal, (inteiro, _, fracao) = ("-" if d < 0 else ""), format(abs(d), "f").partition(".")
    fracao = fracao.rstrip("0")
    grupos = []
    while inteiro:
        grupos.insert(0, inteiro[-3:])
        inteiro = inteiro[:-3]
    exibicao = sinal + (".".join(grupos) or "0") + (f",{fracao}" if fracao else "")
    return Valor(valor=format(d, "f"), exibicao=exibicao)


def _resumo(linha: dict) -> ResumoPesquisa:
    return ResumoPesquisa(
        id=str(linha["id"]), nome=linha.get("nome") or "",
        objeto=linha.get("objeto") or "", estado=linha.get("estado") or "",
        valor_global=valor_monetario(linha.get("valor_global")),
        atualizado_em=str(linha.get("atualizado_em") or ""))


def _item(linha: dict) -> Item:
    return Item(
        id=str(linha["id"]), numero=int(linha["numero"]),
        codigo=linha.get("codigo"), tipo_catalogo=linha.get("tipo_catalogo"),
        descricao=linha.get("descricao") or "", unidade=linha.get("unidade") or "",
        quantidade=valor_quantidade(linha.get("quantidade")),
        estado=linha.get("estado") or "", metodo=linha.get("metodo"),
        preco_estimado=valor_monetario(linha.get("preco_estimado")),
        preco_total=valor_monetario(linha.get("preco_total")),
        justificativa=linha.get("justificativa") or "",
        lote=linha.get("lote"), uf=linha.get("uf"),
        revisao=int(linha.get("revisao") or 1))


def _referencia(linha: dict) -> Referencia:
    vinculos = links.resolver(linha)
    motivos = linha.get("motivos") or []
    return Referencia(
        id=str(linha["id"]),
        fonte=linha.get("fonte_nome") or vinculos.fonte_rotulo or str(linha.get("fonte_id") or ""),
        fonte_tipo=linha.get("fonte_tipo") or "outro",
        natureza_valor=linha.get("natureza_valor") or "outro",
        status=linha.get("status") or "candidate",
        descricao_original=linha.get("descricao_original") or "",
        unidade_original=linha.get("unidade_original"),
        valor_unitario_original=valor_monetario(linha.get("valor_unitario_original")),
        unidade_normalizada=linha.get("unidade_normalizada"),
        valor_unitario_normalizado=valor_monetario(linha.get("valor_unitario_normalizado")),
        orgao=linha.get("orgao"), uf=linha.get("uf"), municipio=linha.get("municipio"),
        fornecedor=linha.get("fornecedor"),
        data_compra=_texto(linha.get("data_compra")),
        data_resultado=_texto(linha.get("data_resultado")),
        coletado_em=str(linha.get("coletado_em") or ""),
        motivos=[str(m) for m in motivos if isinstance(m, (str, int))][:20],
        # Só o que passou por `links.seguro`: https e host oficial.
        link_contratacao=vinculos.contratacao_url,
        rotulo_contratacao=vinculos.contratacao_rotulo,
        link_fonte=links.seguro(vinculos.fonte_url),
        identificacao=vinculos.identificacao)


def _texto(valor) -> str | None:
    return None if valor in (None, "") else str(valor)


def _cursor(linha: dict) -> str:
    bruto = json.dumps([linha["atualizado_em"], str(linha["id"])])
    return base64.urlsafe_b64encode(bruto.encode()).decode().rstrip("=")


def _ler_cursor(cursor: str) -> tuple[str, str]:
    try:
        bruto = base64.urlsafe_b64decode(cursor + "=" * (-len(cursor) % 4))
        momento, ident = json.loads(bruto)
        datetime.fromisoformat(momento)
        return momento, str(uuid.UUID(ident))
    except Exception:  # noqa: BLE001
        raise ErroApi(400, "INVALID_CURSOR", "Cursor inválido") from None


def _ok(resposta: RespostaRest) -> list:
    if resposta.status == 200 and isinstance(resposta.dados, list):
        return resposta.dados
    if resposta.codigo_pg == "42501" or resposta.status == 403:
        raise ErroApi(403, "FORBIDDEN", "Acesso negado")
    raise ErroApi(400, "BAD_REQUEST", "Requisição inválida")


# ---------------------------------------------------------------------------
# Rotas
# ---------------------------------------------------------------------------
def exigir_precos_habilitado(request: Request) -> None:
    if not request.app.state.config.precos_habilitado:
        # 404, não 403: com a flag desligada a rota "não existe" para o
        # cliente, e nada se revela sobre o módulo.
        raise ErroApi(404, "NOT_FOUND", "Recurso não encontrado")


def rotas() -> APIRouter:
    r = APIRouter(prefix="/precos", tags=["precos"],
                  dependencies=[Depends(exigir_precos_habilitado)])

    def _rest(request: Request) -> ClienteRest:
        rest = getattr(request.app.state, "rest", None)
        if rest is None:
            raise ErroApi(503, "AUTH_UNAVAILABLE", "Autenticação indisponível neste ambiente")
        return rest

    def _obter_pesquisa(rest: ClienteRest, eu: Identidade, pesquisa_id: str) -> dict:
        linhas = _ok(rest.requisitar(eu.token, "GET", TABELA_PESQUISAS, decimal=True, params={
            "select": _COLUNAS_PESQUISA, "id": f"eq.{pesquisa_id}",
            "tenant_id": f"eq.{eu.tenant_id}", "limit": "1"}))
        if not linhas:
            raise ErroApi(404, "NOT_FOUND", "Recurso não encontrado")
        return linhas[0]

    @r.get("/pesquisas", response_model=PaginaDePesquisas)
    def listar(request: Request,
               limit: int = Query(20, ge=1, le=100),
               cursor: str | None = Query(None, max_length=512),
               arquivadas: bool = Query(False),
               eu: Identidade = Depends(exigir_identidade)) -> PaginaDePesquisas:
        params: list[tuple[str, str]] = [
            ("select", "id,nome,objeto,estado,valor_global,atualizado_em"),
            ("tenant_id", f"eq.{eu.tenant_id}"),
            ("order", "atualizado_em.desc,id.desc"), ("limit", str(limit + 1))]
        if not arquivadas:
            params.append(("estado", "neq.archived"))
        if cursor:
            momento, ident = _ler_cursor(cursor)
            params.append(("or", f'(atualizado_em.lt."{momento}",'
                                  f'and(atualizado_em.eq."{momento}",id.lt.{ident}))'))
        linhas = _ok(_rest(request).requisitar(eu.token, "GET", TABELA_PESQUISAS,
                                               params=params, decimal=True))
        proximo = _cursor(linhas[limit - 1]) if len(linhas) > limit else None
        return PaginaDePesquisas(itens=[_resumo(l) for l in linhas[:limit]],
                                 proximo_cursor=proximo)

    @r.get("/pesquisas/{pesquisa_id}", response_model=Pesquisa,
           responses={404: {"description": "Inexistente ou fora do seu acesso"}})
    def consultar(pesquisa_id: uuid.UUID, request: Request,
                  eu: Identidade = Depends(exigir_identidade)) -> Pesquisa:
        rest = _rest(request)
        linha = _obter_pesquisa(rest, eu, str(pesquisa_id))
        itens = _ok(rest.requisitar(eu.token, "GET", TABELA_ITENS, decimal=True, params={
            "select": _COLUNAS_ITEM, "pesquisa_id": f"eq.{pesquisa_id}",
            "tenant_id": f"eq.{eu.tenant_id}", "order": "numero.asc",
            # Item retirado da cotação (0029) não some do banco — a 0021
            # não concede DELETE — mas sai da leitura, como no domínio
            # (`cotacoes.py`): mostrá-lo faria a soma divergir do total.
            "removido_em": "is.null",
            "limit": str(LIMITE_ITENS)}))
        resumo = _resumo(linha)
        return Pesquisa(
            **resumo.model_dump(), data_base=_texto(linha.get("data_base")),
            responsavel=linha.get("responsavel") or "",
            local_referencia=linha.get("local_referencia") or "",
            processo_id=_texto(linha.get("processo_id")),
            versao=int(linha.get("versao") or 1),
            criado_em=str(linha.get("criado_em") or ""),
            itens=[_item(i) for i in itens])

    @r.get("/pesquisas/{pesquisa_id}/itens/{item_id}/referencias",
           response_model=list[Referencia],
           responses={404: {"description": "Inexistente ou fora do seu acesso"}})
    def referencias(pesquisa_id: uuid.UUID, item_id: uuid.UUID, request: Request,
                    eu: Identidade = Depends(exigir_identidade)) -> list[Referencia]:
        rest = _rest(request)
        # O item precisa ser DESTA pesquisa: sem isto, um id de item de
        # outra pesquisa do mesmo órgão passaria pela URL de qualquer uma.
        dono = _ok(rest.requisitar(eu.token, "GET", TABELA_ITENS, params={
            "select": "id", "id": f"eq.{item_id}", "pesquisa_id": f"eq.{pesquisa_id}",
            "tenant_id": f"eq.{eu.tenant_id}", "removido_em": "is.null", "limit": "1"}))
        if not dono:
            raise ErroApi(404, "NOT_FOUND", "Recurso não encontrado")
        linhas = _ok(rest.requisitar(eu.token, "GET", TABELA_REFERENCIAS, decimal=True, params={
            "select": _COLUNAS_REFERENCIA, "item_id": f"eq.{item_id}",
            "tenant_id": f"eq.{eu.tenant_id}",
            "order": "valor_unitario_normalizado.asc.nullslast,id.asc",
            "limit": str(LIMITE_REFERENCIAS)}))
        return [_referencia(l) for l in linhas]

    return r

