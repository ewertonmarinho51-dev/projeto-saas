"""
`/api/v1/precos/referencias/cmed` — teto CMED de medicamentos.

Consulta PRÓPRIA, fora da cesta de compras: a CMED não publica preço
praticado, publica o PREÇO MÁXIMO que a lei permite. A rota só lê a lista
vigente da 0050 com o token do usuário (RLS) e devolve, por apresentação e na
alíquota de ICMS pedida, o PF, o PMVG e o TETO NA VENDA AO GOVERNO pela regra
do cabeçalho da CMED (CAP → PMVG; sem CAP → PF), com as marcas de isenção, a
data da lista, o arquivo oficial e a linha.

Desligada (flag `referencia_teto_cmed`), a rota responde 404.
"""

from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel

from src import db, governanca
from src.precos import cmed
from src.precos import repositorio as repo
from src.streamlit_opcional import sessao_da_requisicao

from .erros import ErroApi
from .precos import Valor, exigir_precos_habilitado, valor_monetario
from .seguranca import Identidade, exigir_identidade

FUNDAMENTO = (
    "Lista de Preços de Medicamentos da CMED (Lei 10.742/2003). O Preço Fábrica "
    "(PF) é o teto para farmácias, drogarias e entes da administração pública; "
    "o Preço Máximo de Venda ao Governo (PMVG) é o PF com o Coeficiente de "
    "Adequação de Preços (CAP) e vale só para os medicamentos do Anexo I da "
    "Resolução CTE-CMED — para os demais, o limite na venda ao governo é o PF. "
    "O valor depende da alíquota de ICMS do estado de destino, que cabe ao "
    "comprador conferir; apresentação isenta (CONFAZ 87 ou ICMS 0%) usa a "
    "coluna 0%. É teto, não preço de mercado: não entra na cesta da pesquisa.")

Aliquota = Literal[cmed.ALIQUOTAS]  # type: ignore[valid-type]


class TetoCmed(BaseModel):
    registro_id: str
    ggrem: str
    registro: str | None
    eans: list[str]
    substancia: str
    laboratorio: str
    produto: str
    apresentacao: str
    tipo_produto: str | None
    regime_preco: str | None
    tarja: str | None
    aliquota: str
    rotulo_aliquota: str
    pf: Valor
    pmvg: Valor
    teto_governo: Valor
    base_do_teto: str
    cap: bool
    isento_icms: bool
    confaz87: bool
    icms_0: bool
    teto_governo_isento: Valor      # a coluna 0%, para a apresentação isenta
    restricao_hospitalar: bool
    analise_recursal: str | None
    natureza: str                    # "teto_regulatorio"
    rotulo_natureza: str
    publicada_em: str
    arquivo: str
    arquivo_url: str
    arquivo_sha256: str
    linha_planilha: int


class ConsultaCmed(BaseModel):
    publicada_em: str | None
    aliquota: str
    tetos: list[TetoCmed]
    fundamento: str
    pagina_oficial: str


def _contrato(t: cmed.TetoCmed) -> TetoCmed:
    return TetoCmed(
        **{k: getattr(t, k) for k in (
            "registro_id", "ggrem", "registro", "eans", "substancia", "laboratorio",
            "produto", "apresentacao", "tipo_produto", "regime_preco", "tarja",
            "aliquota", "base_do_teto", "cap", "isento_icms", "confaz87", "icms_0",
            "restricao_hospitalar", "analise_recursal", "natureza", "publicada_em",
            "arquivo", "arquivo_sha256", "linha_planilha")},
        rotulo_aliquota=cmed.rotulo_aliquota(t.aliquota),
        pf=valor_monetario(t.pf), pmvg=valor_monetario(t.pmvg),
        teto_governo=valor_monetario(t.teto_governo),
        teto_governo_isento=valor_monetario(t.teto_governo_isento),
        rotulo_natureza=cmed.ROTULO_NATUREZA, arquivo_url=t.url_arquivo)


def rotas() -> APIRouter:
    r = APIRouter(prefix="/precos", tags=["precos"],
                  dependencies=[Depends(exigir_precos_habilitado)])

    @r.get("/referencias/cmed", response_model=ConsultaCmed,
           responses={404: {"description": "Consulta desligada"},
                      422: {"description": "Filtro fora da regra"}})
    def consultar(
            termo: str = Query(default="", max_length=300),
            codigo: str | None = Query(default=None, pattern=r"^\d{8,15}$"),
            aliquota: Aliquota = "18",
            limite: int = Query(default=50, ge=1, le=200),
            eu: Identidade = Depends(exigir_identidade)) -> ConsultaCmed:
        try:
            with sessao_da_requisicao(eu.token, eu.tenant_id):
                try:
                    ligada = db.flag_ativa(governanca.FLAG_REFERENCIA_CMED)
                except Exception:  # noqa: BLE001 — flag ilegível não liga
                    ligada = False
                if not ligada:
                    raise ErroApi(404, "MODULE_UNAVAILABLE",
                                  "Consulta à CMED desligada")
                try:
                    achados = cmed.consultar(repo.buscar_cmed, termo=termo,
                                             codigo=codigo, aliquota=aliquota,
                                             limite=limite)
                except ValueError as erro:
                    raise ErroApi(422, "VALIDATION_ERROR", str(erro)) from None
                except db.ErroBanco:
                    raise
                except Exception:  # noqa: BLE001 — índice fora não vira 500
                    raise ErroApi(503, "SOURCE_UNAVAILABLE",
                                  "O índice da CMED não respondeu") from None
        except db.ErroBanco as erro:
            raise ErroApi(503, "DATABASE_UNAVAILABLE", str(erro)[:300]) from None
        return ConsultaCmed(
            publicada_em=achados[0].publicada_em if achados else None,
            aliquota=aliquota, tetos=[_contrato(x) for x in achados],
            fundamento=FUNDAMENTO, pagina_oficial=cmed.URL_PAGINA)

    return r
