#!/usr/bin/env python
"""
Benchmark do seletor (G4) — parte DETERMINÍSTICA, sobre um conjunto
SINTÉTICO rotulado POR CONSTRUÇÃO.

O que isto é: cada caso é montado de propósito para ser comparável ou não
(mesmo texto e unidade; unidade sem fator; estimado de outro órgão;
vizinho de outro produto; data fora da janela; especificação diferente),
e passa pela cadeia REAL — `busca.coletar` (procedência, unidade,
matching) → `seletor.classificar`. Mede matriz de confusão do que a regra
declara COMPARÁVEL, taxa de abstenção (REVIEW_REQUIRED) e falso positivo.

O que isto NÃO é: calibração do Jev. Rótulo por construção não
substitui rótulo humano sobre referência real, e nenhuma chamada de IA é
feita (custo 0, latência de IA não medida). A promoção do aceite
automático continua exigindo `docs/jev/calibracao_aprovada.json` com
dataset humano (ver `seletor.aceite_automatico_permitido`).

    python scripts/seletor_benchmark.py --saida docs/jev/seletor-benchmark-sintetico.json
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import date, timedelta
from decimal import Decimal
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ))

from src.precos import busca, repositorio, seletor  # noqa: E402
from src.precos.fontes import ResultadoBusca  # noqa: E402
from src.precos.modelo import Fonte, NaturezaValor, Referencia  # noqa: E402

FONTE = Fonte("compras_gov_precos", "Compras.gov — preços praticados",
              "sistema_oficial")
BASE = date(2026, 10, 16)

CANETA = "CANETA ESFEROGRAFICA AZUL PONTA MEDIA 1,0 MM CORPO TRANSPARENTE"
PAPEL = "PAPEL SULFITE A4 75G BRANCO"
PARAFUSO = "PARAFUSO TITANIO XQ9Z"

# (item, unidade do item, descrição na fonte, unidade na fonte, natureza,
#  dias antes da data-base, rótulo: pode sustentar o preço?, motivo)
CASOS = [
    (CANETA, "UNIDADE", CANETA, "UNIDADE", "homologado", 30, True, "idêntico"),
    (CANETA, "UNIDADE", CANETA.lower(), "UN", "homologado", 60, True, "idêntico, caixa/sigla"),
    (PAPEL, "RESMA", PAPEL, "RESMA", "homologado", 10, True, "idêntico"),
    (PAPEL, "RESMA", PAPEL + " RESMA 500 FOLHAS", "RESMA", "praticado", 90, True, "mesmo produto, texto maior"),
    (CANETA, "UNIDADE", CANETA, "CAIXA", "homologado", 30, False, "caixa sem fator"),
    (CANETA, "UNIDADE", CANETA, "UNIDADE", "estimado_origem", 30, False, "estimado de outro órgão"),
    (CANETA, "UNIDADE", CANETA, "UNIDADE", "homologado", 400, False, "fora da janela"),
    (CANETA, "UNIDADE", "LAPISEIRA 0,7 MM GRAFITE", "UNIDADE", "homologado", 30, False, "outro produto"),
    (PAPEL, "RESMA", "PAPEL A3 90G COLORIDO", "RESMA", "homologado", 30, False, "especificação diferente"),
    (PAPEL, "RESMA", "ENVELOPE PARDO A4", "UNIDADE", "homologado", 30, False, "outro produto"),
    *[(PARAFUSO, "UNIDADE", viz, "UNIDADE", "homologado", 20, False, "vizinho aparentado")
      for viz in ("PARAFUSO SEXTAVADO ZINCADO M6", "PARAFUSO 9X-6380",
                  "ESPATULA TITANIO N 9", "PARAFUSO FENDA FERRO",
                  "BROCA TITANIO 6MM")],
]


class _Fonte:
    def __init__(self, referencia):
        self.fonte = FONTE
        self.referencia = referencia

    def pesquisar(self, consulta):
        return ResultadoBusca(fonte=FONTE, referencias=[self.referencia])


def _linha_classificada(n, caso):
    item_desc, item_un, desc, un, natureza, dias, rotulo, motivo = caso
    ref = Referencia(
        fonte=FONTE, id_externo=f"c{n}", bruto={"caso": n, "desc": desc},
        descricao_original=desc, unidade_original=un,
        quantidade_original=Decimal("10"),
        valor_unitario_original=Decimal("10.00"),
        natureza_valor=NaturezaValor(natureza), orgao="Órgão sintético",
        uf="PA", data_compra=BASE - timedelta(days=dias))
    item = {"id": f"i{n}", "numero": 1, "descricao": item_desc,
            "unidade": item_un, "quantidade": "10"}
    coleta = busca.coletar(item, [_Fonte(ref)],
                           filtros={"data_base": BASE.isoformat()})
    [(referencia, comparabilidade)] = coleta.referencias
    linha = repositorio.linha_de_referencia(referencia, comparabilidade,
                                            tenant_id="t", item_id=item["id"])
    linha["id"] = f"ref-{n}"
    analise = seletor.classificar(item, linha,
                                  {"id": "c", "data_base": BASE.isoformat()})
    return {"caso": n, "motivo_do_rotulo": motivo, "rotulo": rotulo,
            "score": linha.get("score"), "classe": analise.classe,
            "decisao": analise.decisao, "explicacao": analise.motivo}


def executar() -> dict:
    casos = [_linha_classificada(n, c) for n, c in enumerate(CASOS, start=1)]
    vp = sum(1 for c in casos if c["decisao"] == seletor.COMPARAVEL and c["rotulo"])
    fp = sum(1 for c in casos if c["decisao"] == seletor.COMPARAVEL and not c["rotulo"])
    vn = sum(1 for c in casos if c["decisao"] == seletor.INCOMPATIVEL and not c["rotulo"])
    fn = sum(1 for c in casos if c["decisao"] == seletor.INCOMPATIVEL and c["rotulo"])
    abst = sum(1 for c in casos if c["decisao"] == seletor.REVISAO)
    decididos = vp + fp
    return {
        "natureza_do_dataset": "SINTÉTICO, rotulado por construção — não "
                               "substitui rotulagem humana",
        "versao_politica": seletor.VERSAO_POLITICA,
        "casos": len(casos),
        "matriz": {"comparavel_correto": vp, "comparavel_errado": fp,
                   "incompativel_correto": vn, "incompativel_errado": fn,
                   "revisao_humana": abst},
        "precisao_comparavel": None if not decididos else round(vp / decididos, 4),
        "falso_positivo": fp,
        "taxa_de_abstencao": round(abst / len(casos), 4),
        "chamadas_ia": 0, "custo_ia": "0",
        "jev": None,
        "detalhe": casos,
    }


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--saida", type=Path)
    args = parser.parse_args(argv)
    resultado = executar()
    texto = json.dumps(resultado, ensure_ascii=False, indent=2)
    if args.saida:
        args.saida.write_text(texto + "\n", encoding="utf-8")
    print(texto)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
