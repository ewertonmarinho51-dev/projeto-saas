"""
Apoio às provas do saneamento pré-cesta (pacote Jev de 17/10/2026).

Carrega a massa SINTÉTICA de 15 itens (`fixtures/precos/jev_cenarios_15_itens.json`,
"NÃO importar para pesquisa real") e a entrega pelo mesmo caminho de uma
fonte real: `Referencia` de domínio → `busca.coletar` (procedência,
deduplicação, `unidades.normalizar`, comparabilidade) → seleção. Nada
aqui chama rede nem IA; o Jev, quando entra, é resposta simulada no
contrato fechado de `decisoes.MOTIVOS`.
"""

from __future__ import annotations

import json
from datetime import date, timedelta
from decimal import Decimal
from pathlib import Path

from src.precos.fontes import ResultadoBusca
from src.precos.modelo import Fonte, NaturezaValor, Referencia

FIXTURE = Path(__file__).resolve().parent / "fixtures" / "precos" / \
    "jev_cenarios_15_itens.json"
FONTE = Fonte("compras_gov_precos", "Compras.gov — preços praticados",
              "sistema_oficial")

# A resposta simulada do Jev para a massa: só onde a fixture descreve
# objeto comprovadamente distinto. Nos demais casos o Jev não opina.
JEV_SIMULADO = {"Q06_05": "different_specification"}


def massa() -> dict:
    dados = json.loads(FIXTURE.read_text(encoding="utf-8"))
    assert dados["meta"]["data_is_real"] is False
    return dados


def itens() -> list[dict]:
    return massa()["items"]


def item_do_banco(item: dict, numero: int) -> dict:
    """O item da fixture como a linha de `pesquisa_preco_itens`."""
    return {"id": item["item_id"], "numero": numero,
            "descricao": item["description"], "unidade": item["target_unit"],
            "quantidade": "10"}


def referencia_da_cotacao(item: dict, cotacao: dict,
                          data_compra: date | None = None) -> Referencia:
    """
    Uma cotação da fixture como a fonte a entregaria. O documento de
    origem (`source_ref`) é o identificador oficial e a origem
    independente; as condições comerciais vão para a descrição, como na
    vida real.
    """
    fatos = "; ".join(cotacao.get("commercial_facts") or [])
    descricao = item["description"] + (f" — {fatos}" if fatos else "")
    capacidade = cotacao.get("units_per_package")
    return Referencia(
        fonte=FONTE, id_externo=cotacao["quote_id"],
        bruto={"id": cotacao["quote_id"], "evidencia": cotacao["evidence_ref"],
               "valor": cotacao["unit_price_brl"]},
        descricao_original=descricao,
        unidade_original=cotacao["source_unit"],
        quantidade_original=Decimal("10"),
        valor_unitario_original=Decimal(cotacao["unit_price_brl"]),
        capacidade_embalagem=None if capacidade is None
        else Decimal(str(capacidade)),
        natureza_valor=NaturezaValor.HOMOLOGADO,
        orgao=f"Órgão sintético {cotacao['source_ref']}",
        ni_fornecedor=f"F-{cotacao['source_ref']}",
        uf="PA",
        data_compra=data_compra or (date.today() - timedelta(days=30)),
        referencia_externa=cotacao["source_ref"])


class FonteDaFixture:
    """`FontePesquisaPreco` dublê: devolve as cotações de UM item."""

    def __init__(self, item: dict):
        self.fonte = FONTE
        self._item = item
        self.chamadas = 0

    def pesquisar(self, consulta) -> ResultadoBusca:
        self.chamadas += 1
        return ResultadoBusca(
            fonte=self.fonte,
            referencias=[referencia_da_cotacao(self._item, c)
                         for c in self._item["quotes"]])


def esperado(item: dict) -> dict:
    return item["expected"]
