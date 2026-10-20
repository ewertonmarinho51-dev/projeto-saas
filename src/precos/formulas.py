"""
Fórmula por REFERÊNCIA — quando a licitação de origem traz as propostas.

O dossiê (J08) mostrou o concorrente convertendo as propostas finais de
uma licitação num valor de referência por fórmula escolhida ("mediana
das 3 melhores", "média das propostas", "menor preço"…). No GovConnect
cada referência é hoje o preço homologado do item, porque NENHUMA fonte
integrada entrega a lista de propostas (pncp.py, compras_gov.py). Por
isso este módulo é deliberadamente pequeno:

* só calcula sobre propostas REAIS que a fonte tenha entregado — sem
  elas, a referência continua sendo o preço homologado, com a natureza
  preservada, e nada é simulado;
* começa pelas fórmulas objetivamente suportadas (pacote, `06_REGRAS`,
  §1): vencedor, menor, mediana, média, mediana e média das N melhores.
  As 27 variações do concorrente NÃO são copiadas;
* `Decimal`, arredondamento declarado (centavo, metade para cima), e a
  memória diz a fórmula e as propostas usadas.

Conferido com os números do dossiê: finais 29,00 · 29,99 · 30,00 ·
30,00 · 33,00 · 33,02 ×4 → mediana das 3 melhores 29,99; média 31,56;
menor 29,00 (`tests/test_cotacoes_g0_reproducao.py`).
"""

from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal

from .estatistica import mediana as _mediana
from .modelo import CENTAVO

FORMULAS = {
    "vencedor": "preço do fornecedor vencedor",
    "menor": "menor proposta final",
    "mediana": "mediana das propostas finais",
    "media": "média das propostas finais",
    "mediana_3_melhores": "mediana das 3 melhores propostas finais",
    "media_3_melhores": "média das 3 melhores propostas finais",
}


class FormulaIndisponivel(ValueError):
    """Não há dado para a fórmula — e nada é simulado no lugar."""


def calcular(formula: str, propostas: list[Decimal], *,
             vencedora: Decimal | None = None) -> Decimal:
    """
    Valor de referência pela fórmula, ao centavo. `propostas` são os
    valores FINAIS que a fonte publicou; `vencedora`, quando a fonte
    identifica, é a proposta adjudicada.
    """
    if formula not in FORMULAS:
        raise FormulaIndisponivel(f"fórmula desconhecida: {formula}")
    valores = sorted(Decimal(v) for v in propostas if v is not None)
    if formula == "vencedor":
        if vencedora is None:
            raise FormulaIndisponivel("a fonte não identificou a vencedora")
        resultado = Decimal(vencedora)
    elif not valores:
        raise FormulaIndisponivel("a fonte não entregou propostas")
    elif formula == "menor":
        resultado = valores[0]
    elif formula == "mediana":
        resultado = _mediana(valores)
    elif formula == "media":
        resultado = sum(valores, Decimal(0)) / Decimal(len(valores))
    else:
        melhores = valores[:3]
        if len(melhores) < 3:
            raise FormulaIndisponivel(
                "menos de 3 propostas: a fórmula das 3 melhores não se aplica")
        resultado = (_mediana(melhores) if formula == "mediana_3_melhores"
                     else sum(melhores, Decimal(0)) / Decimal(3))
    return resultado.quantize(CENTAVO, rounding=ROUND_HALF_UP)


def propostas_do_bruto(bruto: dict) -> list[Decimal]:
    """
    Propostas finais presentes no payload da fonte, se houver.

    Nenhum adapter integrado as entrega hoje; a chave é a que um adapter
    futuro deve preencher (`propostas_finais`: lista de valores). Ausente
    = lista vazia, e `calcular` recusa em vez de inventar.
    """
    saida = []
    for valor in (bruto or {}).get("propostas_finais") or []:
        try:
            saida.append(Decimal(str(valor)))
        except (ArithmeticError, ValueError):
            continue
    return saida


def memoria(formula: str, propostas: list[Decimal], valor: Decimal) -> str:
    lista = ", ".join(f"{v:f}" for v in sorted(propostas))
    return (f"{FORMULAS[formula]} sobre {len(propostas)} proposta(s) "
            f"final(is) publicadas pela fonte ({lista}) = {valor:f}")
