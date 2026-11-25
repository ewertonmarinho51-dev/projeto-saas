"""
`/api/v1/precos/referencias/sigtap` — remuneração da Tabela Unificada do SUS.

Consulta PRÓPRIA, fora da cesta de compras: o valor do SIGTAP é o que o SUS
REMUNERA por procedimento, não preço praticado nem custo de obra. A rota só
lê o índice da 0048 com o token do usuário (RLS: só as linhas vigentes) e
devolve, em cada procedimento, o que a tela precisa para conferir na fonte:
código, competência, modalidades, as parcelas SA, SH e SP, os totais
ambulatorial (SA) e hospitalar (SH + SP), o arquivo oficial e a linha.

Desligada (flag `referencia_sus_sigtap`), a rota responde 404.
"""

from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel

from src import db, governanca
from src.precos import repositorio as repo
from src.precos import sigtap
from src.streamlit_opcional import sessao_da_requisicao

from .erros import ErroApi
from .precos import Valor, exigir_precos_habilitado, valor_monetario
from .seguranca import Identidade, exigir_identidade

FUNDAMENTO = (
    "Valores de remuneração da Tabela Unificada de Procedimentos, "
    "Medicamentos e OPM do SUS (SIGTAP/DATASUS), por competência. SA é o "
    "serviço ambulatorial; no hospitalar, SH é o serviço hospitalar e SP o "
    "serviço profissional, e o total é SH + SP. É o que o SUS paga ao "
    "prestador, não preço de mercado: não entra na cesta da pesquisa de "
    "preços, e usá-lo como parâmetro é decisão registrada no processo.")

Modalidade = Literal["Ambulatorial", "Hospitalar", "Hospital Dia",
                     "Atenção Domiciliar"]


class Procedimento(BaseModel):
    registro_id: str
    codigo: str                    # 10 dígitos
    codigo_formatado: str          # 02.02.01.047-3
    nome: str
    competencia: str               # AAAA-MM
    competencia_exibicao: str      # MM/AAAA
    modalidades: list[str]
    complexidade: str | None       # como a fonte codifica (0–3)
    sexo: str | None
    financiamento: str | None
    rubrica: str | None
    grupo: str | None
    subgrupo: str | None
    forma_organizacao: str | None
    valor_sa: Valor
    valor_sh: Valor
    valor_sp: Valor
    total_ambulatorial: Valor
    total_hospitalar: Valor
    sem_valor: bool
    natureza: str                  # "remuneracao_sus"
    rotulo_natureza: str
    arquivo: str
    arquivo_url: str               # endereço oficial do ZIP (FTP do DATASUS)
    arquivo_sha256: str
    linha_arquivo: int


class ConsultaSigtap(BaseModel):
    competencia: str | None
    procedimentos: list[Procedimento]
    fundamento: str
    pagina_oficial: str


def _contrato(x: dict) -> Procedimento:
    return Procedimento(
        **{k: x.get(k) for k in (
            "registro_id", "codigo", "codigo_formatado", "nome", "competencia",
            "competencia_exibicao", "modalidades", "complexidade", "sexo",
            "financiamento", "rubrica", "grupo", "subgrupo",
            "forma_organizacao", "sem_valor", "natureza", "rotulo_natureza",
            "arquivo", "arquivo_sha256", "linha_arquivo")},
        **{k: valor_monetario(x[k]) for k in (
            "valor_sa", "valor_sh", "valor_sp", "total_ambulatorial",
            "total_hospitalar")},
        arquivo_url=x["url_arquivo"])


def rotas() -> APIRouter:
    r = APIRouter(prefix="/precos", tags=["precos"],
                  dependencies=[Depends(exigir_precos_habilitado)])

    @r.get("/referencias/sigtap", response_model=ConsultaSigtap,
           responses={404: {"description": "Consulta desligada"},
                      422: {"description": "Filtro fora da regra"}})
    def consultar(
            termo: str = Query(default="", max_length=300),
            codigo: str | None = Query(default=None, pattern=r"^\d{10}$"),
            competencia: str | None = Query(default=None,
                                            pattern=r"^\d{4}-(0[1-9]|1[0-2])$"),
            modalidade: Modalidade | None = None,
            limite: int = Query(default=50, ge=1, le=200),
            eu: Identidade = Depends(exigir_identidade)) -> ConsultaSigtap:
        try:
            with sessao_da_requisicao(eu.token, eu.tenant_id):
                try:
                    ligada = db.flag_ativa(governanca.FLAG_REFERENCIA_SIGTAP)
                except Exception:  # noqa: BLE001 — flag ilegível não liga
                    ligada = False
                if not ligada:
                    raise ErroApi(404, "MODULE_UNAVAILABLE",
                                  "Consulta ao SIGTAP desligada")
                try:
                    achados = sigtap.consultar(
                        repo.buscar_sigtap, termo=termo, codigo=codigo,
                        competencia=competencia, modalidade=modalidade,
                        limite=limite)
                except ValueError as erro:
                    raise ErroApi(422, "VALIDATION_ERROR", str(erro)) from None
                except db.ErroBanco:
                    raise
                except Exception:  # noqa: BLE001 — índice fora não vira 500
                    raise ErroApi(503, "SOURCE_UNAVAILABLE",
                                  "O índice do SIGTAP não respondeu") from None
        except db.ErroBanco as erro:
            raise ErroApi(503, "DATABASE_UNAVAILABLE", str(erro)[:300]) from None
        return ConsultaSigtap(
            competencia=achados[0]["competencia"] if achados else competencia,
            procedimentos=[_contrato(x) for x in achados],
            fundamento=FUNDAMENTO, pagina_oficial=sigtap.URL_PAGINA)

    return r
