"""
`/api/v1/precos/pesquisas/...` — gestão da cotação e dos itens (M10a).

O que a tela unificada de Cotações do Streamlit (`ui/cotacoes_ui`) faz e
`/app/precos` ainda não fazia: duplicar e arquivar a cotação; incluir,
editar e retirar item à mão; desfazer a própria retirada de um preço e
"manter preço" no alerta de atípico. O domínio é o mesmo
(`precos.cotacoes`), dentro da sessão do usuário; o RLS da 0021
(`pode_escrever_pesquisa_preco`: admin ou dono) é quem garante, e a
guarda daqui só devolve o código certo.

Escrita sobre item já existente pede `If-Match` com a revisão do item —
a mesma trava otimista da cesta e da conclusão.
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Body, Depends, Header, Request
from pydantic import BaseModel, ConfigDict, Field

from src.precos import cotacoes
from src.precos import repositorio as repo
from src.streamlit_opcional import sessao_da_requisicao

from .cesta import ResultadoDaCesta, _revisao
from .erros import ErroApi
from .precos import TABELA_ITENS, TABELA_PESQUISAS, Valor, exigir_precos_habilitado, valor_monetario
from .precos_escrita import _TRADUZIVEIS, ItemDepois, PesquisaCriada, _traduzir
from .seguranca import Identidade, exigir_identidade
from .supabase_rest import ClienteRest


class _Entrada(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class DadosDoItem(_Entrada):
    descricao: str = Field(min_length=3, max_length=2000)
    unidade: str = Field(min_length=1, max_length=40)
    # Decimal em texto ("1.234,5" ou "1234.5"): o domínio converte, nunca float.
    quantidade: str = Field(min_length=1, max_length=30)
    codigo: str = Field(default="", max_length=40)
    lote: str = Field(default="", max_length=40)
    uf: str = Field(default="", max_length=2)


class AlertaDePreco(BaseModel):
    """O card "Confira este preço" (04_UX): qual preço e a faixa dos demais."""
    referencia_id: str
    # Mantido por decisão registrada: o alerta acompanha o preço, sem ação.
    mantida: bool
    faixa_min: Valor | None
    faixa_max: Valor | None


class Retirada(_Entrada):
    # Opcional (pacote Jev, RF-02): a auditoria é automática.
    motivo: str = Field(default="", max_length=1000)


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

    def _pesquisa(rest: ClienteRest, eu: Identidade, pesquisa_id: uuid.UUID, *, escrever: bool) -> dict:
        resposta = rest.requisitar(eu.token, "GET", TABELA_PESQUISAS, params={
            "select": "id,nome,estado,auth_user_id", "id": f"eq.{pesquisa_id}",
            "tenant_id": f"eq.{eu.tenant_id}", "limit": "1"})
        if resposta.status != 200 or not resposta.dados:
            raise ErroApi(404, "NOT_FOUND", "Recurso não encontrado")
        linha = resposta.dados[0]
        # Espelha `pode_escrever_pesquisa_preco` (0021): admin ou dono.
        if escrever and eu.papel != "admin" and str(linha.get("auth_user_id") or "") != eu.auth_user_id:
            raise ErroApi(403, "FORBIDDEN", "Só quem criou a pesquisa (ou o administrador) pode alterá-la.")
        return linha

    def _item(rest: ClienteRest, eu: Identidade, pesquisa_id, item_id) -> dict:
        resposta = rest.requisitar(eu.token, "GET", TABELA_ITENS, params={
            "select": "id,estado", "id": f"eq.{item_id}", "pesquisa_id": f"eq.{pesquisa_id}",
            "tenant_id": f"eq.{eu.tenant_id}", "removido_em": "is.null", "limit": "1"})
        if resposta.status != 200 or not resposta.dados:
            raise ErroApi(404, "NOT_FOUND", "Recurso não encontrado")
        return resposta.dados[0]

    def _depois(item_id: str) -> ItemDepois:
        linha = repo.obter_item(item_id) or {}
        return ItemDepois(id=item_id, estado=str(linha.get("estado") or ""),
                          revisao=int(linha.get("revisao") or 0))

    def _executar(eu: Identidade, funcao):
        try:
            with sessao_da_requisicao(eu.token, eu.tenant_id):
                return funcao()
        except _TRADUZIVEIS as exc:
            raise _traduzir(exc) from None

    # -- cotação -----------------------------------------------------------
    @r.post("/pesquisas/{pesquisa_id}/duplicacao", status_code=201, response_model=PesquisaCriada,
            responses={404: {"description": "Inexistente ou fora do seu acesso"}})
    def duplicar(pesquisa_id: uuid.UUID, request: Request,
                 eu: Identidade = Depends(exigir_identidade)) -> PesquisaCriada:
        """Cópia NOVA, mesmos itens e nenhum preço: a coleta é refeita na nova data-base.
        Ler basta: a cópia é de quem duplica."""
        _pesquisa(_rest(request), eu, pesquisa_id, escrever=False)

        def copiar():
            copia = cotacoes.duplicar(_ctx(eu), str(pesquisa_id))
            return PesquisaCriada(id=str(copia["id"]), nome=str(copia.get("nome") or ""),
                                  estado=str(copia.get("estado") or ""))
        return _executar(eu, copiar)

    @r.post("/pesquisas/{pesquisa_id}/arquivamento", response_model=PesquisaCriada,
            responses={403: {"description": "Só o dono ou o administrador"},
                       404: {"description": "Inexistente ou fora do seu acesso"},
                       409: {"description": "Transição de estado não permitida"}})
    def arquivar(pesquisa_id: uuid.UUID, request: Request,
                 eu: Identidade = Depends(exigir_identidade)) -> PesquisaCriada:
        atual = _pesquisa(_rest(request), eu, pesquisa_id, escrever=True)
        if atual.get("estado") == "archived":
            return PesquisaCriada(id=str(pesquisa_id), nome=str(atual.get("nome") or ""), estado="archived")

        def guardar():
            linha = cotacoes.arquivar(_ctx(eu), str(pesquisa_id)) or {}
            return PesquisaCriada(id=str(pesquisa_id), nome=str(linha.get("nome") or atual.get("nome") or ""),
                                  estado=str(linha.get("estado") or "archived"))
        return _executar(eu, guardar)

    # -- item --------------------------------------------------------------
    def _campos(corpo: DadosDoItem) -> dict:
        return {"descricao": corpo.descricao, "unidade": corpo.unidade, "quantidade": corpo.quantidade,
                "codigo": corpo.codigo, "lote": corpo.lote, "uf": corpo.uf}

    @r.post("/pesquisas/{pesquisa_id}/itens", status_code=201, response_model=ItemDepois,
            responses={403: {"description": "Só o dono ou o administrador"},
                       409: {"description": "Cotação imutável"},
                       422: {"description": "Regra do domínio recusou (unidade, quantidade…)"}})
    def incluir_item(pesquisa_id: uuid.UUID, corpo: DadosDoItem, request: Request,
                     eu: Identidade = Depends(exigir_identidade)) -> ItemDepois:
        _pesquisa(_rest(request), eu, pesquisa_id, escrever=True)

        def incluir():
            novo = cotacoes.salvar_item(_ctx(eu), str(pesquisa_id), _campos(corpo))
            return _depois(str(novo["id"]))
        return _executar(eu, incluir)

    @r.put("/pesquisas/{pesquisa_id}/itens/{item_id}", response_model=ItemDepois,
           responses={403: {"description": "Só o dono ou o administrador"},
                      404: {"description": "Inexistente ou fora do seu acesso"},
                      409: {"description": "Revisão desatualizada ou cotação imutável"},
                      428: {"description": "If-Match ausente"}})
    def editar_item(pesquisa_id: uuid.UUID, item_id: uuid.UUID, corpo: DadosDoItem, request: Request,
                    if_match: str | None = Header(None, alias="If-Match"),
                    eu: Identidade = Depends(exigir_identidade)) -> ItemDepois:
        revisao = _revisao(if_match)
        rest = _rest(request)
        _pesquisa(rest, eu, pesquisa_id, escrever=True)
        _item(rest, eu, pesquisa_id, item_id)

        def editar():
            cotacoes.salvar_item(_ctx(eu), str(pesquisa_id), _campos(corpo), item_id=str(item_id),
                                 revisao_esperada=revisao)
            return _depois(str(item_id))
        return _executar(eu, editar)

    @r.post("/pesquisas/{pesquisa_id}/itens/{item_id}/retirada", response_model=ItemDepois,
            responses={403: {"description": "Só o dono ou o administrador"},
                       404: {"description": "Inexistente ou fora do seu acesso"},
                       409: {"description": "Cotação imutável"}})
    def retirar_item(pesquisa_id: uuid.UUID, item_id: uuid.UUID, request: Request,
                     corpo: Retirada = Body(default_factory=Retirada),
                     eu: Identidade = Depends(exigir_identidade)) -> ItemDepois:
        """Retira SEM apagar: o item e as referências ficam no banco e na trilha."""
        rest = _rest(request)
        _pesquisa(rest, eu, pesquisa_id, escrever=True)
        _item(rest, eu, pesquisa_id, item_id)

        def retirar():
            cotacoes.remover_item(_ctx(eu), str(pesquisa_id), str(item_id), corpo.motivo or None)
            return _depois(str(item_id))
        return _executar(eu, retirar)

    # -- preço na cesta ----------------------------------------------------
    @r.get("/pesquisas/{pesquisa_id}/itens/{item_id}/alertas", response_model=list[AlertaDePreco],
           responses={404: {"description": "Inexistente ou fora do seu acesso"}})
    def alertas(pesquisa_id: uuid.UUID, item_id: uuid.UUID, request: Request,
                eu: Identidade = Depends(exigir_identidade)) -> list[AlertaDePreco]:
        """Os preços da cesta que merecem conferência — a régua do Streamlit e da emissão."""
        rest = _rest(request)
        _pesquisa(rest, eu, pesquisa_id, escrever=False)
        _item(rest, eu, pesquisa_id, item_id)

        def calcular():
            item = repo.obter_item(str(item_id)) or {}
            saida = []
            for alerta in cotacoes.alertas_do_item(item, repo.listar_referencias(str(item_id))):
                outros = alerta["outros"]
                saida.append(AlertaDePreco(
                    referencia_id=str(alerta["linha"]["id"]), mantida=bool(alerta.get("mantida")),
                    faixa_min=valor_monetario(min(outros)) if outros else None,
                    faixa_max=valor_monetario(max(outros)) if outros else None))
            return saida
        return _executar(eu, calcular)

    def _cesta(eu, pesquisa_id, item_id, funcao) -> ResultadoDaCesta:
        def rodar():
            estimativa = funcao()
            item = repo.obter_item(str(item_id)) or {}
            return ResultadoDaCesta(
                preco_estimado=valor_monetario(estimativa.valor_unitario),
                metodo=estimativa.metodo, status=estimativa.status,
                pendencias=list(estimativa.pendencias)[:20],
                revisao=int(item.get("revisao") or 0))
        return _executar(eu, rodar)

    def _item_aberto(rest, eu, pesquisa_id, item_id) -> None:
        _pesquisa(rest, eu, pesquisa_id, escrever=True)
        if _item(rest, eu, pesquisa_id, item_id).get("estado") == "complete":
            raise ErroApi(409, "ITEM_COMPLETE",
                          "Item concluído: reabra o item, com o motivo, antes de mudar a cesta.")

    @r.post("/pesquisas/{pesquisa_id}/itens/{item_id}/referencias/{referencia_id}/desfazer",
            response_model=ResultadoDaCesta,
            responses={409: {"description": "Revisão desatualizada, item concluído ou cotação imutável"},
                       422: {"description": "Não há retirada sua para desfazer"},
                       428: {"description": "If-Match ausente"}})
    def desfazer_retirada(pesquisa_id: uuid.UUID, item_id: uuid.UUID, referencia_id: uuid.UUID,
                          request: Request, if_match: str | None = Header(None, alias="If-Match"),
                          eu: Identidade = Depends(exigir_identidade)) -> ResultadoDaCesta:
        """O "Desfazer" da retirada sem motivo: só a última, e só a sua."""
        revisao = _revisao(if_match)
        _item_aberto(_rest(request), eu, pesquisa_id, item_id)
        return _cesta(eu, pesquisa_id, item_id, lambda: cotacoes.desfazer_retirada(
            _ctx(eu), str(pesquisa_id), str(item_id), str(referencia_id), revisao_esperada=revisao))

    @r.post("/pesquisas/{pesquisa_id}/itens/{item_id}/referencias/{referencia_id}/manter",
            response_model=ResultadoDaCesta,
            responses={409: {"description": "Revisão desatualizada, item concluído ou cotação imutável"},
                       422: {"description": "O preço não está na cesta"},
                       428: {"description": "If-Match ausente"}})
    def manter(pesquisa_id: uuid.UUID, item_id: uuid.UUID, referencia_id: uuid.UUID,
               request: Request, if_match: str | None = Header(None, alias="If-Match"),
               eu: Identidade = Depends(exigir_identidade)) -> ResultadoDaCesta:
        """"Manter preço" no alerta de atípico: fica na cesta, sinalizado, e a decisão é registrada."""
        revisao = _revisao(if_match)
        _item_aberto(_rest(request), eu, pesquisa_id, item_id)
        return _cesta(eu, pesquisa_id, item_id, lambda: cotacoes.manter_referencia(
            _ctx(eu), str(pesquisa_id), str(item_id), str(referencia_id), revisao_esperada=revisao))

    return r
