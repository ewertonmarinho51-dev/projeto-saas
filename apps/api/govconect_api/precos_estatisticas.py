"""
`/api/v1/precos/.../estatisticas` — a série de preços de um item, resumida.

O que a tela de análise mostra (dispersão, média, mediana, CV, comparação
por fonte e por UF, faixa usual) sai daqui, calculado no servidor. A conta
NÃO mora aqui: é `src/precos/estatistica.calcular` e `detectar_anomalias`,
as mesmas do relatório e da emissão. Esta rota só escolhe a série, agrupa
e traduz para o contrato de dinheiro da P04a (`Valor`: string decimal +
exibição pela regra do domínio). O navegador não soma, não divide e não
arredonda nada que se EXIBA: no gráfico ele só posiciona o ponto, e todo
rótulo vem desta resposta.

Duas séries, nomeadas pelo que são:

* **cesta** — as referências que entram no cálculo (`selected` e
  `warning`, a mesma regra de `naCesta` na tela);
* **coletadas** — todas as que têm valor normalizado, qualquer situação.
  Serve para o revisor ver o que a triagem deixou de fora.

Estatística descreve a série; não é a estimativa. O preço estimado do item
continua sendo o que `estatistica.estimar` gravou, pelo método do item.

"Fora da faixa" é sinalização estatística (IQR/MAD contra a CESTA), nunca
juízo de inexequibilidade — a mesma fronteira do domínio.

O eixo dos gráficos também sai daqui, e é sempre LINEAR e completo: vai do
menor ao maior coletado, em marcas redondas. Quando um extremo achata o resto
da série, `recorte` oferece um SEGUNDO eixo ampliado na faixa central e conta
o que ficou de fora; o eixo completo continua sendo o principal. Escala
quebrada ou logarítmica esconderia a distância que o revisor precisa ver.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from decimal import ROUND_CEILING, ROUND_FLOOR, ROUND_HALF_UP, Decimal
from typing import Literal

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel

from src.precos import estatistica

from .erros import ErroApi
from .precos import (_COLUNAS_REFERENCIA, LIMITE_REFERENCIAS, TABELA_ITENS, TABELA_REFERENCIAS,
                     Valor, _decimal, _ok, _referencia, exigir_precos_habilitado)
from .seguranca import Identidade, exigir_identidade
from .supabase_rest import ClienteRest

NA_CESTA = frozenset({"selected", "warning"})
SEM_UF = "Sem UF"
_QUATRO_CASAS = Decimal("0.0001")
_CENTAVO = Decimal("0.01")
INTERVALOS_DO_EIXO = 5
# Só vale ampliar quando a faixa central ocupa menos que esta fração do eixo.
FRACAO_DO_RECORTE = Decimal("0.5")
# Abaixo disto a linha de tendência é ruído, não série.
MINIMO_DA_TENDENCIA = 3


# ---------------------------------------------------------------------------
# Contratos
# ---------------------------------------------------------------------------
class Percentual(BaseModel):
    """Fração exata (`"0.1234"`) e o que se mostra (`"12,34%"`)."""

    valor: str
    exibicao: str


class FaixaUsual(BaseModel):
    """Q1 − 1,5·IQR (sem passar de zero) a Q3 + 1,5·IQR — o critério de Tukey."""

    minimo: Valor
    maximo: Valor


class ResumoDaSerie(BaseModel):
    quantidade: int
    menor: Valor
    maior: Valor
    media: Valor
    mediana: Valor
    q1: Valor
    q3: Valor
    amplitude: Valor
    desvio_padrao: Valor
    coeficiente_variacao: Percentual
    # "insuficiente" abaixo de 2 preços: CV de um preço só é zero e não diz nada.
    dispersao: Literal["homogenea", "dispersa", "insuficiente"]
    # Só a partir de 4 preços, como `detectar_anomalias`.
    faixa_usual: FaixaUsual | None


class GrupoDePrecos(BaseModel):
    rotulo: str
    na_cesta: int
    resumo: ResumoDaSerie


class PontoDePreco(BaseModel):
    referencia_id: str
    fonte: str
    uf: str | None
    status: str
    valor: Valor
    na_cesta: bool
    # Critérios ("IQR", "MAD") pelos quais o preço fica longe da cesta.
    fora_da_faixa: list[str]
    # Menor ou maior de TODAS as coletadas; empate marca os dois preços iguais.
    extremo: Literal["menor", "maior"] | None = None
    # Distância até a mediana da cesta, com sinal ("+233,33%").
    sobre_a_mediana: Percentual | None = None


class EscalaDoGrafico(BaseModel):
    """Eixo linear: `minimo` e `maximo` posicionam; `marcas` já vêm escritas."""

    minimo: Valor
    maximo: Valor
    marcas: list[Valor]


class RecorteCentral(BaseModel):
    """Eixo ampliado na faixa central, sempre ao lado do eixo completo."""

    escala: EscalaDoGrafico
    abaixo: int
    acima: int


class EstatisticasDoItem(BaseModel):
    cesta: ResumoDaSerie | None
    coletadas: ResumoDaSerie | None
    por_fonte: list[GrupoDePrecos]
    por_uf: list[GrupoDePrecos]
    pontos: list[PontoDePreco]
    # Referências sem valor normalizado: ficam fora de toda conta, e a tela diz quantas.
    sem_valor: int
    limite_dispersao: Percentual
    escala: EscalaDoGrafico | None = None
    recorte: RecorteCentral | None = None
    # Preços da cesta por data de compra; só existe a partir de 3 preços datados.
    tendencia: list[Valor] = []


# ---------------------------------------------------------------------------
# Tradução
# ---------------------------------------------------------------------------
def _percentual(fracao: Decimal) -> Percentual:
    return Percentual(valor=format(fracao.quantize(_QUATRO_CASAS, rounding=ROUND_HALF_UP), "f"),
                      exibicao=estatistica.pct(fracao))


def _dinheiro(valor: Decimal) -> Valor:
    """Valor calculado na escala do banco (`numeric(18,4)`); a exibição sai do
    valor INTEIRO, para não arredondar duas vezes (x,xx4999 → x,xx50 → x,xx+1)."""
    return Valor(valor=format(valor.quantize(_QUATRO_CASAS, rounding=ROUND_HALF_UP), "f"),
                 exibicao=estatistica.brl(valor))


def _variacao(valor: Decimal, base: Decimal) -> Percentual | None:
    if base <= estatistica.ZERO:
        return None
    fracao = (valor - base) / base
    sinal = "+" if fracao > estatistica.ZERO else ""
    return Percentual(valor=format(fracao.quantize(_QUATRO_CASAS, rounding=ROUND_HALF_UP), "f"),
                      exibicao=sinal + estatistica.pct(fracao))


def _passo(amplitude: Decimal) -> Decimal:
    """1, 2 ou 5 × 10ⁿ: o menor passo que cobre a amplitude nos intervalos do eixo."""
    bruto = amplitude / INTERVALOS_DO_EIXO
    potencia = Decimal(1).scaleb(bruto.adjusted())
    passo = next(potencia * f for f in (1, 2, 5, 10) if potencia * f >= bruto)
    return max(passo, _CENTAVO)     # marca menor que um centavo repetiria o mesmo texto


def escala_de(menor: Decimal, maior: Decimal) -> EscalaDoGrafico:
    """Eixo linear que contém `menor` e `maior`, em marcas redondas."""
    if menor == maior:
        folga = menor / 10 if menor > estatistica.ZERO else Decimal(1)
        menor, maior = max(menor - folga, estatistica.ZERO), maior + folga
    passo = _passo(maior - menor)
    inicio = (menor / passo).to_integral_value(rounding=ROUND_FLOOR) * passo
    fim = (maior / passo).to_integral_value(rounding=ROUND_CEILING) * passo
    quantas = int((fim - inicio) / passo)
    return EscalaDoGrafico(minimo=_dinheiro(inicio), maximo=_dinheiro(fim),
                           marcas=[_dinheiro(inicio + passo * i) for i in range(quantas + 1)])


def _recorte(calculo: estatistica.Estatisticas | None, todos: list[Decimal],
             completa: EscalaDoGrafico) -> RecorteCentral | None:
    """Eixo ampliado na faixa de Tukey da cesta, quando um extremo achata o resto."""
    if calculo is None or calculo.quantidade < 4:
        return None
    baixo = max(calculo.q1 - estatistica.FATOR_IQR * calculo.iqr, estatistica.ZERO)
    alto = calculo.q3 + estatistica.FATOR_IQR * calculo.iqr
    dentro = [v for v in todos if baixo <= v <= alto]
    if not dentro or len(dentro) == len(todos):
        return None
    escala = escala_de(min(dentro), max(dentro))
    inicio, fim = Decimal(escala.minimo.valor), Decimal(escala.maximo.valor)
    largura_total = Decimal(completa.maximo.valor) - Decimal(completa.minimo.valor)
    if fim - inicio >= largura_total * FRACAO_DO_RECORTE:
        return None
    # Conta contra o eixo arredondado: é ele que decide o que aparece no gráfico.
    return RecorteCentral(escala=escala, abaixo=sum(1 for v in todos if v < inicio),
                          acima=sum(1 for v in todos if v > fim))


def resumir(valores: list[Decimal]) -> ResumoDaSerie | None:
    e = estatistica.calcular(valores)
    if e is None:
        return None
    if e.quantidade < 2:
        dispersao = "insuficiente"
    elif e.coeficiente_variacao > estatistica.CV_DISPERSAO:
        dispersao = "dispersa"
    else:
        dispersao = "homogenea"
    faixa = None
    if e.quantidade >= 4:
        faixa = FaixaUsual(
            minimo=_dinheiro(max(e.q1 - estatistica.FATOR_IQR * e.iqr, estatistica.ZERO)),
            maximo=_dinheiro(e.q3 + estatistica.FATOR_IQR * e.iqr))
    return ResumoDaSerie(
        quantidade=e.quantidade, menor=_dinheiro(e.menor), maior=_dinheiro(e.maior),
        media=_dinheiro(e.media), mediana=_dinheiro(e.mediana), q1=_dinheiro(e.q1),
        q3=_dinheiro(e.q3), amplitude=_dinheiro(e.amplitude),
        desvio_padrao=_dinheiro(e.desvio_padrao),
        coeficiente_variacao=_percentual(e.coeficiente_variacao),
        dispersao=dispersao, faixa_usual=faixa)


@dataclass
class _Candidato:
    """O mínimo que `detectar_anomalias` lê e escreve. A marcação que ele faz
    (`status`, `motivos`) fica aqui, descartável: esta rota só LÊ."""

    valor_unitario_normalizado: Decimal
    status: str = ""
    motivos: list[str] = field(default_factory=list)

    def com_motivo(self, motivo: str) -> "_Candidato":
        self.motivos.append(motivo)
        return self


def _agrupar(linhas: list[tuple[str, Decimal, bool]]) -> list[GrupoDePrecos]:
    grupos: dict[str, list[tuple[Decimal, bool]]] = {}
    for rotulo, valor, na_cesta in linhas:
        grupos.setdefault(rotulo, []).append((valor, na_cesta))
    saida = []
    for rotulo, membros in grupos.items():
        resumo = resumir([v for v, _ in membros])
        assert resumo is not None
        saida.append(GrupoDePrecos(rotulo=rotulo, na_cesta=sum(1 for _, c in membros if c),
                           resumo=resumo))
    # Mais preços primeiro; empate pela mediana, depois pelo nome — ordem estável.
    return sorted(saida, key=lambda g: (-g.resumo.quantidade,
                                        Decimal(g.resumo.mediana.valor), g.rotulo))


def estatisticas_do_item(linhas: list[dict]) -> EstatisticasDoItem:
    """Pura: linhas de `pesquisa_preco_referencias` (lidas com decimal=True)."""
    validas = []
    linhas_validas = []
    sem_valor = 0
    for linha in linhas:
        valor = _decimal(linha.get("valor_unitario_normalizado"))
        if valor is None:
            sem_valor += 1
            continue
        ref = _referencia(linha)
        validas.append((ref, valor, (linha.get("status") or "") in NA_CESTA))
        linhas_validas.append(linha)

    da_cesta = [v for _, v, c in validas if c]
    todos = [v for _, v, _ in validas]

    longe: dict[int, list[str]] = {}
    calc_cesta = estatistica.calcular(da_cesta)
    if calc_cesta is not None:
        candidatos = [_Candidato(v) for _, v, _ in validas]
        for anomalia in estatistica.detectar_anomalias(candidatos, calc_cesta):  # type: ignore[arg-type]
            longe[id(anomalia.referencia)] = anomalia.criterio.split("+")
        criterios = [longe.get(id(c), []) for c in candidatos]
    else:
        criterios = [[] for _ in validas]

    menor, maior = (min(todos), max(todos)) if todos else (None, None)

    def extremo(valor: Decimal) -> Literal["menor", "maior"] | None:
        if menor == maior:
            return None     # todos iguais: não há extremo a apontar
        return "menor" if valor == menor else "maior" if valor == maior else None

    pontos = [
        PontoDePreco(referencia_id=ref.id, fonte=ref.fonte, uf=ref.uf, status=ref.status,
                     valor=_dinheiro(valor), na_cesta=na_cesta, fora_da_faixa=crit,
                     extremo=extremo(valor),
                     sobre_a_mediana=_variacao(valor, calc_cesta.mediana) if calc_cesta else None)
        for (ref, valor, na_cesta), crit in zip(validas, criterios)]

    cesta = resumir(da_cesta)
    escala = None
    if todos:
        # A faixa usual entra no eixo: ela é desenhada e não pode sair do gráfico.
        faixa = [Decimal(v.valor) for v in
                 ((cesta.faixa_usual.minimo, cesta.faixa_usual.maximo)
                  if cesta and cesta.faixa_usual else ())]
        escala = escala_de(min([*todos, *faixa]), max([*todos, *faixa]))
    datadas = sorted(((linha.get("data_compra"), v) for (r, v, c), linha in
                      zip(validas, linhas_validas) if c and linha.get("data_compra")),
                     key=lambda par: par[0])

    return EstatisticasDoItem(
        cesta=cesta, coletadas=resumir(todos),
        por_fonte=_agrupar([(r.fonte, v, c) for r, v, c in validas]),
        por_uf=_agrupar([((r.uf or "").upper() or SEM_UF, v, c) for r, v, c in validas]),
        pontos=pontos, sem_valor=sem_valor,
        limite_dispersao=_percentual(estatistica.CV_DISPERSAO),
        escala=escala, recorte=_recorte(calc_cesta, todos, escala) if escala else None,
        tendencia=[_dinheiro(v) for _, v in datadas] if len(datadas) >= MINIMO_DA_TENDENCIA else [])


# ---------------------------------------------------------------------------
# Rota
# ---------------------------------------------------------------------------
def rotas() -> APIRouter:
    r = APIRouter(prefix="/precos", tags=["precos"],
                  dependencies=[Depends(exigir_precos_habilitado)])

    @r.get("/pesquisas/{pesquisa_id}/itens/{item_id}/estatisticas",
           response_model=EstatisticasDoItem,
           responses={404: {"description": "Inexistente ou fora do seu acesso"}})
    def estatisticas(pesquisa_id: uuid.UUID, item_id: uuid.UUID, request: Request,
                     eu: Identidade = Depends(exigir_identidade)) -> EstatisticasDoItem:
        rest: ClienteRest | None = getattr(request.app.state, "rest", None)
        if rest is None:
            raise ErroApi(503, "AUTH_UNAVAILABLE", "Autenticação indisponível neste ambiente")
        # Item DESTA pesquisa, como em `referencias`: senão o id de um item de
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
        return estatisticas_do_item(linhas)

    return r
