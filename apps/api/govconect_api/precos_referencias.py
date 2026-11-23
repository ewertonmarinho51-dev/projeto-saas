"""
`/api/v1/precos/referencias/sinapi` — consulta ao custo de referência do SINAPI.

Não é pesquisa de preço de compra: é a consulta própria do custo de
engenharia (Lei 14.133, art. 23, § 2º, I), separada da cesta. A conta e a
validação moram em `src/precos/sinapi.py`; esta rota só lê o índice com o
token do usuário (RPC `precos_sinapi_buscar`, 0046) e traduz para o contrato
de dinheiro da P04a.

Fechada por padrão: com a consulta desabilitada (`fontes_externas`: flag,
mapeamento e licença), a rota responde 404 — "não existe" para o cliente.
"""

from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel

from src import db
from src.precos import fontes_externas, sinapi
from src.precos import repositorio as repo
from src.streamlit_opcional import sessao_da_requisicao

from .erros import ErroApi
from .precos import Valor, exigir_precos_habilitado, valor_monetario
from .seguranca import Identidade, exigir_identidade


class CustoSinapi(BaseModel):
    """Uma linha publicada pela CAIXA, com a origem que permite conferi-la."""

    codigo: str
    descricao: str
    unidade: str
    valor: Valor
    tipo: Literal["insumo", "composicao"]
    rotulo_tipo: str
    regime: Literal["sem_desoneracao", "com_desoneracao", "sem_encargos"]
    rotulo_regime: str
    uf: str
    competencia: str            # "2026-10"
    competencia_exibicao: str   # "10/2026"
    classificacao: str | None
    # insumo: C (coletado) ou CR (coeficiente de representatividade)
    origem_preco: str | None
    rotulo_origem: str
    # composição: parte do custo obtida com preço de São Paulo (%AS)
    percentual_sp: str | None
    natureza: Literal["custo_referencia_engenharia"]
    rotulo_natureza: str
    fonte: str
    url_fonte: str
    url_verificacao: str        # o arquivo oficial da competência
    aba: str
    linha_planilha: int
    arquivo_sha256: str
    chave_linha: str


class ConsultaSinapi(BaseModel):
    itens: list[CustoSinapi]
    aviso: str


AVISO = ("Custo de referência de obra e serviço de engenharia (SINAPI). Não é "
         "preço de compra e não entra na cesta da pesquisa de preços.")


def consulta_aberta() -> bool:
    """As três travas de `fontes_externas`; flag ilegível = fechada."""
    return fontes_externas.habilitada("sinapi")


def rotas() -> APIRouter:
    r = APIRouter(prefix="/precos/referencias", tags=["precos"],
                  dependencies=[Depends(exigir_precos_habilitado)])

    @r.get("/sinapi", response_model=ConsultaSinapi,
           responses={404: {"description": "Consulta não habilitada"},
                      422: {"description": "Filtro fora da regra"}})
    def consultar(
        termo: str = Query(default="", max_length=200),
        codigo: str = Query(default="", max_length=12, pattern=r"^\d*$"),
        uf: str = Query(default="PA", min_length=2, max_length=2),
        competencia: str = Query(default="", pattern=r"^(\d{4}-(0[1-9]|1[0-2]))?$"),
        tipo: Literal["", "insumo", "composicao"] = "",
        regime: Literal["sem_desoneracao", "com_desoneracao",
                        "sem_encargos"] = "sem_desoneracao",
        limite: int = Query(default=50, ge=1, le=200),
        eu: Identidade = Depends(exigir_identidade),
    ) -> ConsultaSinapi:
        try:
            with sessao_da_requisicao(eu.token, eu.tenant_id):
                if not consulta_aberta():
                    raise ErroApi(404, "NOT_FOUND", "Recurso não encontrado")
                linhas = sinapi.consultar(
                    repo.buscar_indice_sinapi, termo=termo, codigo=codigo or None,
                    uf=uf.upper(), competencia=competencia or None,
                    tipo=tipo or None, regime=regime, limite=limite)
        except ValueError as exc:
            raise ErroApi(422, "VALIDATION_ERROR", str(exc)) from None
        except repo.SemSessao:
            raise ErroApi(401, "UNAUTHENTICATED", "Sessão ausente, expirada ou inválida",
                          {"WWW-Authenticate": "Bearer"}) from None
        except db.ErroBanco:
            raise ErroApi(503, "DATABASE_UNAVAILABLE",
                          "O índice do SINAPI não respondeu agora.") from None
        itens = []
        for linha in linhas:
            valor = valor_monetario(linha["valor"])
            if valor is None:
                continue
            itens.append(CustoSinapi(**{
                **{k: linha[k] for k in CustoSinapi.model_fields
                   if k not in ("valor", "linha_planilha")},
                "valor": valor, "linha_planilha": int(linha["linha_planilha"])}))
        return ConsultaSinapi(itens=itens, aviso=AVISO)

    return r
