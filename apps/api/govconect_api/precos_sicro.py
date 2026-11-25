"""
`/api/v1/precos/referencias/sicro` — custo referencial do SICRO (DNIT).

Consulta PRÓPRIA, fora da cesta de compras, como a do SINAPI: o SICRO é o
sistema de custos de obras de infraestrutura de transportes (Lei 14.133,
art. 23, § 2º, I, e § 3º). A rota só lê o índice da 0049 com o token do
usuário (RLS: só as linhas vigentes) e devolve, em cada linha, o que a tela
precisa para conferir na fonte: tipo, código, UF, competência, regime de
encargos, unidade, custo (equipamento: produtivo e improdutivo), a origem
do preço na UF, o 7-Zip oficial, a planilha de dentro dele e a linha.

Desligada (flag `referencia_custos_sicro`), a rota responde 404.
"""

from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal
from typing import Literal

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel

from src import db, governanca
from src.precos import repositorio as repo
from src.precos import sicro
from src.streamlit_opcional import sessao_da_requisicao

from .erros import ErroApi
from .precos import Valor, exigir_precos_habilitado
from .seguranca import Identidade, exigir_identidade

FUNDAMENTO = (
    "Lei 14.133/2021, art. 23, § 2º, I: em obras e serviços de engenharia, o "
    "valor estimado tem como parâmetro o custo de referência do SINAPI ou, "
    "para infraestrutura de transportes, do SICRO. O § 3º admite outro "
    "sistema de custos adotado pelo ente, nas condições ali previstas — a "
    "escolha e o regime de encargos são do orçamentista e ficam registrados "
    "no processo. BDI não está incluído. As composições do SICRO são "
    "publicadas só com encargos sem desoneração.")


class ReferenciaSicro(BaseModel):
    registro_id: str
    tipo: Literal["composicao", "material", "mao_de_obra", "equipamento"]
    rotulo_tipo: str
    codigo: str
    descricao: str
    unidade: str | None
    uf: str
    competencia: str              # AAAA-MM
    regime: str
    rotulo_regime: str
    valor: Valor                  # equipamento: custo horário produtivo
    valor_improdutivo: Valor | None
    natureza: str                 # "custo_referencial"
    origem_preco: str | None      # sigla do DNIT na UF (PC, PFM, PRE…)
    rotulo_origem: str | None
    identificacao: str
    arquivo: str                  # o 7-Zip oficial
    arquivo_url: str
    arquivo_sha256: str
    planilha: str                 # o relatório de dentro do 7-Zip
    linha_planilha: int


class ConsultaSicro(BaseModel):
    competencia: str | None
    referencias: list[ReferenciaSicro]
    fundamento: str
    pagina_oficial: str


def valor_publicado(valor: Decimal | None, casas: int) -> Valor | None:
    """Exato, com as casas que o DNIT publica: composição em centavos,
    insumo com quatro casas (R$ 24,8197 por hora de ajudante)."""
    if valor is None:
        return None
    q = valor.quantize(Decimal(1).scaleb(-casas), rounding=ROUND_HALF_UP)
    inteiro, _, fracao = f"{q:f}".partition(".")
    grupos = []
    while inteiro:
        grupos.insert(0, inteiro[-3:])
        inteiro = inteiro[:-3]
    return Valor(valor=format(valor, "f"), exibicao=f"R$ {'.'.join(grupos)},{fracao}")


def _contrato(r: sicro.ReferenciaSicro) -> ReferenciaSicro:
    casas = 2 if r.tipo == sicro.COMPOSICAO else sicro.CASAS
    return ReferenciaSicro(
        registro_id=r.registro_id, tipo=r.tipo, rotulo_tipo=r.rotulo_tipo,
        codigo=r.codigo, descricao=r.descricao, unidade=r.unidade, uf=r.uf,
        competencia=r.competencia, regime=r.regime, rotulo_regime=r.rotulo_regime,
        valor=valor_publicado(r.valor, casas),
        valor_improdutivo=valor_publicado(r.valor_improdutivo, casas),
        natureza=r.natureza, origem_preco=r.origem_preco,
        rotulo_origem=r.rotulo_origem, identificacao=r.identificacao,
        arquivo=r.arquivo, arquivo_url=r.url_arquivo,
        arquivo_sha256=r.arquivo_sha256, planilha=r.planilha,
        linha_planilha=r.linha_planilha)


def rotas() -> APIRouter:
    r = APIRouter(prefix="/precos", tags=["precos"],
                  dependencies=[Depends(exigir_precos_habilitado)])

    @r.get("/referencias/sicro", response_model=ConsultaSicro,
           responses={404: {"description": "Consulta desligada"},
                      422: {"description": "Filtro fora da regra"}})
    def consultar(
            termo: str = Query(default="", max_length=300),
            codigo: str | None = Query(default=None,
                                       pattern=r"^(\d{7}|[MPEAmpea]\d{4})$"),
            uf: str = Query(default="PA", pattern=r"^[A-Za-z]{2}$"),
            competencia: str | None = Query(default=None,
                                            pattern=r"^\d{4}-(0[1-9]|1[0-2])$"),
            regime: Literal["sem_desoneracao", "com_desoneracao"] = "sem_desoneracao",
            tipo: Literal["composicao", "material", "mao_de_obra",
                          "equipamento"] | None = None,
            limite: int = Query(default=50, ge=1, le=200),
            eu: Identidade = Depends(exigir_identidade)) -> ConsultaSicro:
        if uf.upper() not in sicro.UFS:
            raise ErroApi(422, "VALIDATION_ERROR", "UF desconhecida")
        try:
            with sessao_da_requisicao(eu.token, eu.tenant_id):
                try:
                    ligada = db.flag_ativa(governanca.FLAG_REFERENCIA_SICRO)
                except Exception:  # noqa: BLE001 — flag ilegível não liga
                    ligada = False
                if not ligada:
                    raise ErroApi(404, "MODULE_UNAVAILABLE",
                                  "Consulta ao SICRO desligada")
                try:
                    achados = sicro.consultar(
                        repo.buscar_sicro, termo=termo, codigo=codigo,
                        uf=uf.upper(), competencia=competencia, regime=regime,
                        tipo=tipo, limite=limite)
                except ValueError as erro:
                    raise ErroApi(422, "VALIDATION_ERROR", str(erro)) from None
                except db.ErroBanco:
                    raise
                except Exception:  # noqa: BLE001 — índice fora não vira 500
                    raise ErroApi(503, "SOURCE_UNAVAILABLE",
                                  "O índice do SICRO não respondeu") from None
        except db.ErroBanco as erro:
            raise ErroApi(503, "DATABASE_UNAVAILABLE", str(erro)[:300]) from None
        return ConsultaSicro(
            competencia=achados[0].competencia if achados else competencia,
            referencias=[_contrato(x) for x in achados],
            fundamento=FUNDAMENTO, pagina_oficial=sicro.URL_PAGINA)

    return r
