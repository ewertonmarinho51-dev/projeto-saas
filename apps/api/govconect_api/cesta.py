"""
Cesta de preços: pôr ou tirar UMA referência e recalcular (P04b).

A regra NÃO mora aqui. Mora em `src/precos/cotacoes.py::
alterar_status_referencia`, a mesma que o Streamlit usa hoje:

* tirar não exige motivo (pacote Jev, RF-02); pôr exige — vai para a
  memória de cálculo;
* reincluir o que a triagem desconsiderou entra SINALIZADO (`warning`);
* a revisão do item é conferida antes de gravar; conflito na escrita
  final DESFAZ a mudança da referência;
* trilha automática com ator, hora, de/para e preço recalculado.

Esta rota só traduz HTTP ↔ domínio. O domínio fala com o banco pelo
JWT do usuário (`db.cliente_do_usuario`), que aqui vem de
`sessao_da_requisicao` com a identidade JÁ verificada — o RLS da 0021
decide de novo, para o dono do token.
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, Header, Request
from pydantic import BaseModel, ConfigDict, Field

from src import db
from src.precos import cotacoes
from src.precos import repositorio as repo
from src.streamlit_opcional import sessao_da_requisicao

from .erros import ErroApi
from .precos import TABELA_ITENS, Valor, exigir_precos_habilitado, valor_monetario
from .seguranca import Identidade, exigir_identidade
from .supabase_rest import ClienteRest


class MudancaNaCesta(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    incluir: bool
    # Opcional para tirar, obrigatório para pôr — quem decide é o domínio,
    # e a mensagem dele volta ao cliente.
    motivo: str | None = Field(default=None, max_length=1000)


class ResultadoDaCesta(BaseModel):
    preco_estimado: Valor | None
    metodo: str
    status: str
    pendencias: list[str]
    # A revisão NOVA do item: é ela que o próximo If-Match manda.
    revisao: int


def _revisao(if_match: str | None) -> int:
    if not if_match:
        raise ErroApi(428, "PRECONDITION_REQUIRED",
                      "If-Match obrigatório: envie a revisão do item que você leu")
    texto = if_match.strip().removeprefix("W/").strip('"')
    if not texto.isdigit() or not 1 <= int(texto) <= 10_000_000:
        raise ErroApi(400, "BAD_REQUEST", "If-Match inválido")
    return int(texto)


def rotas() -> APIRouter:
    r = APIRouter(prefix="/precos", tags=["precos"],
                  dependencies=[Depends(exigir_precos_habilitado)])

    @r.patch("/pesquisas/{pesquisa_id}/itens/{item_id}/referencias/{referencia_id}",
             response_model=ResultadoDaCesta,
             responses={404: {"description": "Inexistente ou fora do seu acesso"},
                        409: {"description": "Revisão desatualizada ou cotação imutável"},
                        422: {"description": "Regra da cesta recusou (ex.: incluir sem motivo)"},
                        428: {"description": "If-Match ausente"}})
    def mudar(pesquisa_id: uuid.UUID, item_id: uuid.UUID, referencia_id: uuid.UUID,
              corpo: MudancaNaCesta, request: Request,
              if_match: str | None = Header(None, alias="If-Match"),
              eu: Identidade = Depends(exigir_identidade)) -> ResultadoDaCesta:
        revisao = _revisao(if_match)
        rest: ClienteRest | None = getattr(request.app.state, "rest", None)
        if rest is None:
            raise ErroApi(503, "AUTH_UNAVAILABLE", "Autenticação indisponível neste ambiente")
        # 404 antes do domínio: item desta pesquisa, deste município, visível
        # para este token. Sem isto, "não encontrado" viraria 422 com a
        # mensagem do domínio, e o código HTTP mentiria sobre o motivo.
        resposta = rest.requisitar(eu.token, "GET", TABELA_ITENS, params={
            "select": "id", "id": f"eq.{item_id}", "pesquisa_id": f"eq.{pesquisa_id}",
            "tenant_id": f"eq.{eu.tenant_id}", "removido_em": "is.null", "limit": "1"})
        if resposta.status != 200 or not resposta.dados:
            raise ErroApi(404, "NOT_FOUND", "Recurso não encontrado")

        ctx = cotacoes.Contexto(auth_user_id=eu.auth_user_id, secretaria_id=eu.secretaria_id)
        with sessao_da_requisicao(eu.token, eu.tenant_id):
            try:
                estimativa = cotacoes.alterar_status_referencia(
                    ctx, str(pesquisa_id), str(item_id), str(referencia_id),
                    incluir=corpo.incluir, motivo=corpo.motivo, revisao_esperada=revisao)
                item = repo.obter_item(str(item_id)) or {}
            except repo.ConflitoDeVersao:
                raise ErroApi(409, "VERSION_CONFLICT",
                              "O item mudou desde a sua leitura. Recarregue e refaça.") from None
            except cotacoes.CotacaoImutavel:
                raise ErroApi(409, "IMMUTABLE",
                              "Cotação aplicada ou arquivada: crie uma revisão nova.") from None
            except cotacoes.ErroCotacao as exc:
                # Mensagem do domínio, escrita para o usuário ("registre o
                # motivo da inclusão..."). Não carrega dado de banco.
                raise ErroApi(422, "DOMAIN_RULE", str(exc)) from None
            except repo.SemSessao:
                raise ErroApi(401, "UNAUTHENTICATED",
                              "Sessão ausente, expirada ou inválida",
                              {"WWW-Authenticate": "Bearer"}) from None
            except db.ErroBanco:
                raise ErroApi(503, "DATABASE_UNAVAILABLE", "Banco de dados indisponível") from None

        return ResultadoDaCesta(
            preco_estimado=valor_monetario(estimativa.valor_unitario),
            metodo=estimativa.metodo, status=estimativa.status,
            pendencias=list(estimativa.pendencias)[:20],
            revisao=int(item.get("revisao") or revisao))

    return r
