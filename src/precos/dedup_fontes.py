"""
Deduplicação entre fontes novas e as já integradas — conservadora.

Regra do pacote (20/10/2026): a mesma compra/item/resultado vista em dois
portais conta UMA vez, mas só se FUNDE com igualdade comprovada de
identidade. Semelhança de texto ou de valor não funde nada: vira
"possível duplicata", que vai para a revisão de uma pessoa.

* `chave_forte` — identidade comprovada do evento: na própria fonte,
  `(fonte, registro_id)`; entre fontes, só quando ambas dão o mesmo
  identificador oficial da compra e do item (o idCompra do Compras.gov
  aparece no link de origem do PNCP — `busca.fundir_entre_portais` já
  faz isso para os dois). O TCE-RS e o BPS NÃO trazem número de
  controle do PNCP nem idCompra: entre eles e as fontes atuais não há
  chave forte;
* `possiveis_duplicatas` — mesmo CNPJ de fornecedor, MESMO valor unitário
  (Decimal exato) e data a até `JANELA_DIAS`. Sinal para revisão, nunca
  fusão: dois órgãos podem comprar do mesmo fornecedor pelo mesmo preço.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal, InvalidOperation

from .evidencia import Evidencia

JANELA_DIAS = 30


def chave_forte(e: Evidencia) -> tuple:
    return (e.fonte_id, e.registro_id)


def _data(texto) -> date | None:
    if isinstance(texto, date):
        return texto
    try:
        return date.fromisoformat(str(texto or "")[:10])
    except ValueError:
        return None


def deduplicar(evidencias: list[Evidencia]) -> tuple[list[Evidencia], int]:
    """Mesma linha da mesma fonte (reprocessamento): fica a primeira."""
    vistas, saida = set(), []
    for e in evidencias:
        chave = chave_forte(e)
        if chave in vistas:
            continue
        vistas.add(chave)
        saida.append(e)
    return saida, len(evidencias) - len(saida)


def possiveis_duplicatas(evidencias: list[Evidencia], referencias: list,
                         *, janela: int = JANELA_DIAS) -> list[tuple]:
    """
    Pares (evidência, referência) que PODEM ser a mesma compra.

    `referencias` são `modelo.Referencia` (ou dicts gravados) das fontes
    atuais. Exige fornecedor CNPJ dos dois lados e valor idêntico; sem
    data de um dos lados, não há par (não se presume contemporaneidade).
    """
    def campo(r, nome):
        return r.get(nome) if isinstance(r, dict) else getattr(r, nome, None)

    pares = []
    for e in evidencias:
        if not e.fornecedor_cnpj or e.valor_unitario is None:
            continue
        de = _data(e.data_resultado)
        for r in referencias:
            ni = "".join(ch for ch in str(campo(r, "ni_fornecedor") or "")
                         if ch.isdigit())
            valor = campo(r, "valor_unitario_original")
            if ni != e.fornecedor_cnpj or valor is None:
                continue
            try:
                if Decimal(str(valor)) != e.valor_unitario:
                    continue
            except InvalidOperation:
                continue
            dr = _data(campo(r, "data_resultado") or campo(r, "data_compra"))
            if de is None or dr is None or abs((de - dr).days) > janela:
                continue
            pares.append((e, r))
    return pares
