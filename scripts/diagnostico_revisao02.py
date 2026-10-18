#!/usr/bin/env python
"""
Diagnóstico da massa SINTÉTICA de 15 itens do pacote Revisão 02 — antes e
depois, pelo mesmo caminho real (`busca.coletar` → `selecionar_cesta` →
`estimar`), sem banco, sem rede, sem IA.

* antes: sem triagem e sem teto (as capturas de produção: "317/3");
* v1: triagem do pacote anterior (5+ preços) com teto de 15;
* depois: triagem v2 (8+ preços, atípico de amostra pequena sinalizado na
  cesta, reavaliação e reposição da cesta formada) com teto de 15.

    python scripts/diagnostico_revisao02.py --saida diag.json
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ))


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--saida", required=True)
    args = parser.parse_args()

    from src.precos import estatistica, saneamento
    from src.precos.perfil import obter as obter_perfil
    from tests import test_revisao02_triagem as massa

    cenarios = {
        "antes_sem_triagem_sem_teto": (None, None),
        "v1_teto_15": (saneamento.POLITICA_V1, 15),
        "depois_v2_teto_15": (saneamento.POLITICA_PADRAO, 15),
    }
    saida = {"aviso": "massa TOTALMENTE SINTÉTICA do pacote; não é pesquisa "
                      "real", "itens": []}
    for item in massa._massa()["items"]:
        linha = {"item": item["id"], "descricao": item["description"],
                 "candidatos": len(item["references"])}
        for nome, (politica, teto) in cenarios.items():
            coleta, escolha = massa._cesta(item, politica=politica, teto=teto) \
                if politica is not None else massa._cesta(item, politica=None,
                                                          teto=None)
            # a triagem marca ANTES do cálculo; o cálculo marca em memória
            # os atípicos que vira alerta na tela — contados separados
            sinalizados = sum(1 for r in escolha.selecionadas
                              if r.status.value == "warning")
            est = estatistica.estimar(escolha, perfil=obter_perfil("in_65_2021"),
                                      regras=estatistica.REGRAS_MEDIA_PADRAO)
            linha[nome] = {
                "usados": len(escolha.selecionadas),
                "sinalizados_na_cesta": sinalizados,
                "alertas_do_calculo": len(est.anomalias),
                "fora_pela_triagem": len(escolha.retidas),
                "valor_unitario": None if est.valor_unitario is None
                else format(est.valor_unitario, "f"),
                "maior_usado": format(max(escolha.valores), "f")
                if escolha.valores else None,
                "pendencias": est.pendencias,
            }
        saida["itens"].append(linha)
    Path(args.saida).write_text(json.dumps(saida, ensure_ascii=False, indent=2),
                                encoding="utf-8")
    for linha in saida["itens"]:
        a, d = linha["antes_sem_triagem_sem_teto"], linha["depois_v2_teto_15"]
        print(f"{linha['item']} {linha['descricao'][:22]:22} "
              f"antes {a['usados']:>2} R$ {a['valor_unitario']:>8} maior "
              f"{a['maior_usado']:>7} | depois {d['usados']:>2} "
              f"(sinal. {d['sinalizados_na_cesta']}, alertas "
              f"{d['alertas_do_calculo']}, fora {d['fora_pela_triagem']}) "
              f"R$ {d['valor_unitario']:>8} maior {d['maior_usado']:>7}")


if __name__ == "__main__":
    main()
