"""
`/api/v1/precos/referencias/sinapi` — custo referencial de engenharia.

Consulta PRÓPRIA, fora da cesta de compras: o SINAPI é o parâmetro de custo
de obras e serviços de engenharia (Lei 14.133, art. 23, § 2º, I), e o valor
dele é "custo referencial", não preço praticado. A rota só lê o índice da
0046 com o token do usuário (RLS: só as linhas vigentes) e devolve, em cada
linha, o que a tela e o relatório precisam para conferir na fonte: tipo,
código, competência, UF, regime de encargos, unidade, origem do preço ou
%AS, a planilha oficial, a aba e a linha.

Desligada (flag `referencia_custos_sinapi`), a rota responde 404.
"""

from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel

from src import db, governanca
from src.precos import repositorio as repo
from src.precos import sinapi
from src.streamlit_opcional import sessao_da_requisicao

from .erros import ErroApi
from .precos import Valor, exigir_precos_habilitado, valor_monetario
from .seguranca import Identidade, exigir_identidade

FUNDAMENTO = (
    "Lei 14.133/2021, art. 23, § 2º, I: em obras e serviços de engenharia, o "
    "valor estimado tem como parâmetro o custo de referência do SINAPI. O § 3º "
    "admite outro sistema de custos adotado pelo ente, nas condições ali "
    "previstas — a escolha e o regime de encargos são do orçamentista e ficam "
    "registrados no processo. BDI não está incluído.")


class ReferenciaDeCusto(BaseModel):
    registro_id: str
    tipo: Literal["insumo", "composicao"]
    codigo: str
    descricao: str
    unidade: str | None
    uf: str
    competencia: str              # AAAA-MM
    regime: str
    rotulo_regime: str
    valor: Valor
    natureza: str                 # "custo_referencial"
    classificacao: str | None
    origem_preco: str | None      # insumo: C (coletado) | CR (coeficiente)
    percentual_sp: str | None     # composição: %AS, fração (0.0011 = 0,11%)
    identificacao: str
    planilha: str                 # endereço oficial do relatório mensal
    aba: str
    linha_planilha: int
    arquivo_sha256: str


class ConsultaDeCustos(BaseModel):
    competencia: str | None
    referencias: list[ReferenciaDeCusto]
    fundamento: str
    pagina_oficial: str


def _contrato(r: sinapi.ReferenciaDeCusto) -> ReferenciaDeCusto:
    return ReferenciaDeCusto(
        registro_id=r.registro_id, tipo=r.tipo, codigo=r.codigo,
        descricao=r.descricao, unidade=r.unidade, uf=r.uf,
        competencia=r.competencia, regime=r.regime,
        rotulo_regime=r.rotulo_regime, valor=valor_monetario(r.valor),
        natureza=r.natureza, classificacao=r.classificacao,
        origem_preco=r.origem_preco,
        percentual_sp=None if r.percentual_sp is None else format(r.percentual_sp, "f"),
        identificacao=r.identificacao, planilha=r.url_arquivo, aba=r.aba,
        linha_planilha=r.linha_planilha, arquivo_sha256=r.arquivo_sha256)


def rotas() -> APIRouter:
    r = APIRouter(prefix="/precos", tags=["precos"],
                  dependencies=[Depends(exigir_precos_habilitado)])

    @r.get("/referencias/sinapi", response_model=ConsultaDeCustos,
           responses={404: {"description": "Consulta desligada"},
                      422: {"description": "Filtro fora da regra"}})
    def consultar(
            termo: str = Query(default="", max_length=300),
            codigo: str | None = Query(default=None, pattern=r"^\d{1,9}$"),
            uf: str = Query(default="PA", pattern=r"^[A-Za-z]{2}$"),
            competencia: str | None = Query(default=None,
                                            pattern=r"^\d{4}-(0[1-9]|1[0-2])$"),
            regime: Literal["sem_desoneracao", "com_desoneracao",
                            "sem_encargos"] = "sem_desoneracao",
            tipo: Literal["insumo", "composicao"] | None = None,
            limite: int = Query(default=50, ge=1, le=200),
            eu: Identidade = Depends(exigir_identidade)) -> ConsultaDeCustos:
        if uf.upper() not in sinapi.UFS:
            raise ErroApi(422, "VALIDATION_ERROR", "UF desconhecida")
        try:
            with sessao_da_requisicao(eu.token, eu.tenant_id):
                try:
                    ligada = db.flag_ativa(governanca.FLAG_REFERENCIA_SINAPI)
                except Exception:  # noqa: BLE001 — flag ilegível não liga
                    ligada = False
                if not ligada:
                    raise ErroApi(404, "MODULE_UNAVAILABLE",
                                  "Consulta ao SINAPI desligada")
                resultado = sinapi.ConsultaSINAPI(repo.buscar_sinapi).consultar(
                    termo=termo, codigo=codigo, uf=uf.upper(),
                    competencia=competencia, regime=regime, tipo=tipo,
                    limite=limite)
        except db.ErroBanco as erro:
            raise ErroApi(503, "DATABASE_UNAVAILABLE", str(erro)[:300]) from None
        if resultado.falha:
            raise ErroApi(503, "SOURCE_UNAVAILABLE", resultado.falha)
        return ConsultaDeCustos(
            competencia=resultado.competencia,
            referencias=[_contrato(x) for x in resultado.referencias],
            fundamento=FUNDAMENTO, pagina_oficial=sinapi.URL_PAGINA)

    return r
