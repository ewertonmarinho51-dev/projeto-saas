"""
Diagnóstico reproduzível do saneamento pré-cesta — massa SINTÉTICA de 15
itens do pacote Jev (17/10/2026). Sem rede, sem IA, sem banco.

Cada item passa pelo caminho real da cotação automática: `busca.coletar`
(procedência, deduplicação, `unidades.normalizar`, comparabilidade) e
`estatistica.selecionar_cesta` — ANTES (sem triagem) e DEPOIS (com
`saneamento.POLITICA_PADRAO` e, no segundo passo, a resposta simulada do
Jev). Mede, por item: coletadas, comparáveis, na cesta, desconsideradas,
em revisão — e classifica o defeito (comparabilidade, unidade,
duplicidade, valor inválido, desvio estatístico).

    python scripts/diagnostico_saneamento.py            # tabela
    python scripts/diagnostico_saneamento.py --json saída.json
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RAIZ))

from src.precos import busca, estatistica, saneamento  # noqa: E402
from src.precos.perfil import obter as obter_perfil  # noqa: E402
from tests import saneamento_apoio as apoio  # noqa: E402

DEFEITO = {
    saneamento.VALOR_INVALIDO: "valor inválido",
    saneamento.UNIDADE_NAO_CONVERSIVEL: "unidade",
    saneamento.DUPLICIDADE: "duplicidade",
    saneamento.NATUREZA_NAO_PRECO: "natureza do valor",
    saneamento.CONTEXTO_COMERCIAL: "condição comercial",
    saneamento.DIVERGENCIA_JEV: "comparabilidade (Jev)",
    saneamento.DISPERSAO_INCONCLUSIVA: "amostra pequena e dispersa",
    saneamento.EXTREMO: "desvio estatístico",
    saneamento.VARIACAO_RELEVANTE: "desvio estatístico",
}


def _defeito(codigos: list[str]) -> str:
    for codigo in (saneamento.VALOR_INVALIDO,
                   saneamento.UNIDADE_NAO_CONVERSIVEL, saneamento.DUPLICIDADE,
                   saneamento.CONTEXTO_COMERCIAL, saneamento.DIVERGENCIA_JEV,
                   saneamento.DISPERSAO_INCONCLUSIVA, saneamento.EXTREMO,
                   saneamento.VARIACAO_RELEVANTE):
        if codigo in codigos:
            return DEFEITO[codigo]
    return "—"


def diagnosticar() -> list[dict]:
    perfil = obter_perfil(None)
    saida = []
    for numero, item in enumerate(apoio.itens(), start=1):
        linha = apoio.item_do_banco(item, numero)
        fonte = [apoio.FonteDaFixture(item)]

        antes = busca.coletar(linha, fonte, filtros={})
        cesta_antes = estatistica.selecionar_cesta(antes.referencias, perfil)

        depois = busca.coletar(linha, fonte, filtros={})
        cesta_depois = estatistica.selecionar_cesta(
            depois.referencias, perfil, saneamento=saneamento.POLITICA_PADRAO,
            texto_item=linha["descricao"])
        triagem = cesta_depois.triagem
        # segundo passo: a evidência simulada do Jev sobre o que entrou
        por_id = triagem.por_id()
        for ref, _ in depois.referencias:
            escolha = apoio.JEV_SIMULADO.get(ref.id_externo)
            if not escolha or ref.chave_dedupe not in por_id:
                continue
            nova = saneamento.reavaliar_com_jev(
                por_id[ref.chave_dedupe], escolha)
            por_id[ref.chave_dedupe] = nova
            if nova.desfecho != saneamento.ELEGIVEL and \
                    ref in cesta_depois.selecionadas:
                cesta_depois.selecionadas.remove(ref)

        avaliacoes = [{"cotacao": ref.id_externo,
                       "valor_original": format(ref.valor_unitario_original, "f"),
                       "valor_normalizado": None
                       if ref.valor_unitario_normalizado is None
                       else format(ref.valor_unitario_normalizado, "f"),
                       "desfecho": por_id[ref.chave_dedupe].desfecho
                       if ref.chave_dedupe in por_id else "fora do piso",
                       "codigos": por_id[ref.chave_dedupe].codigos
                       if ref.chave_dedupe in por_id else [],
                       "defeito": _defeito(por_id[ref.chave_dedupe].codigos)
                       if ref.chave_dedupe in por_id else "comparabilidade"}
                      for ref, _ in depois.referencias]
        saida.append({
            "item": item["item_id"], "descricao": item["description"],
            "coletadas": antes.brutas, "unicas": antes.unicas,
            "antes": {"na_cesta": [r.id_externo
                                   for r in cesta_antes.selecionadas],
                      "fora": len(cesta_antes.descartadas)},
            "depois": {
                "na_cesta": [r.id_externo for r in cesta_depois.selecionadas],
                "desconsideradas": [a["cotacao"] for a in avaliacoes
                                    if a["desfecho"] == saneamento.DESCONSIDERADA],
                "revisao": [a["cotacao"] for a in avaliacoes
                            if a["desfecho"] == saneamento.REVISAO]},
            "serie": triagem.serie,
            "avaliacoes": avaliacoes,
            "esperado": apoio.esperado(item),
        })
    return saida


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[1])
    parser.add_argument("--json", help="grava o diagnóstico neste arquivo")
    args = parser.parse_args()
    linhas = diagnosticar()
    print(f"{'item':8} {'col':>3} {'cesta antes':>11} {'cesta depois':>12} "
          f"{'descons.':>8} {'revisão':>7}  defeitos")
    for d in linhas:
        defeitos = sorted({a["defeito"] for a in d["avaliacoes"]
                           if a["desfecho"] != saneamento.ELEGIVEL})
        print(f"{d['item']:8} {d['coletadas']:>3} "
              f"{len(d['antes']['na_cesta']):>11} "
              f"{len(d['depois']['na_cesta']):>12} "
              f"{len(d['depois']['desconsideradas']):>8} "
              f"{len(d['depois']['revisao']):>7}  {', '.join(defeitos) or '—'}")
    if args.json:
        Path(args.json).write_text(json.dumps(
            {"massa": "sintética (pacote Jev 17/10/2026) — NÃO é dado real",
             "politica": saneamento.POLITICA_PADRAO.para_registro(),
             "itens": linhas}, ensure_ascii=False, indent=2),
            encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
