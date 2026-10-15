#!/usr/bin/env python
"""
Benchmark da Pesquisa de Preços — o mesmo roteiro antes e depois.

Roda o pipeline REAL (`execucao.pesquisar_item`) sobre os itens do caso
de 210 itens (`tests/fixtures/caso_210_itens.json`), contra as fontes
públicas oficiais, e mede o que o pacote do Banco de Preços pede:

  * latência por item (p50/p95) e total;
  * chamadas HTTP por item, por fonte;
  * cobertura bruta (referências encontradas), elegível (na cesta) e 3+;
  * erros de fonte distinguidos de "sem resultado".

Só lê APIs públicas (Compras.gov, PNCP, catálogo de materiais): nenhuma
gravação em banco, nenhuma chamada de IA, nenhuma credencial.

Uso:
    python scripts/benchmark_precos.py --itens 10 --saida docs/bench/antes-10.json
    python scripts/benchmark_precos.py --itens 210 --inicio 0
"""

from __future__ import annotations

import argparse
import json
import statistics
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ))

from src.precos import execucao  # noqa: E402
from src.precos import fontes_padrao  # noqa: E402

FIXTURE = RAIZ / "tests" / "fixtures" / "caso_210_itens.json"


def _percentil(valores: list[float], p: float) -> float | None:
    if not valores:
        return None
    ordenados = sorted(valores)
    k = max(0, min(len(ordenados) - 1, round(p * (len(ordenados) - 1))))
    return round(ordenados[k], 2)


def _contar_chamadas(fontes) -> dict[str, int]:
    """Envolve o transporte de cada fonte para contar requisições."""
    contagem: dict[str, int] = {}
    for fonte in fontes:
        fid = fonte.fonte.id
        contagem[fid] = 0
        original = fonte._abrir  # noqa: SLF001

        def contado(url, _orig=original, _fid=fid):
            contagem[_fid] += 1
            return _orig(url)

        fonte._abrir = contado  # noqa: SLF001
        catalogo = getattr(fonte, "_catalogo", None)
        if catalogo is not None:
            orig_cat = catalogo._abrir  # noqa: SLF001

            def cat(url, _orig=orig_cat):
                contagem["catalogo"] = contagem.get("catalogo", 0) + 1
                return _orig(url)

            catalogo._abrir = cat  # noqa: SLF001
    return contagem


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--itens", type=int, default=10)
    parser.add_argument("--inicio", type=int, default=0)
    parser.add_argument("--saida", default="")
    args = parser.parse_args()

    caso = json.loads(FIXTURE.read_text(encoding="utf-8"))
    itens = caso["itens"][args.inicio:args.inicio + args.itens]
    fontes = fontes_padrao()
    # O catálogo do processo (índice de PDMs) é compartilhado, como no app.
    from src.precos import catalogo as catalogo_mod
    for fonte in fontes:
        if hasattr(fonte, "_catalogo") and fonte._catalogo is None:  # noqa: SLF001
            fonte._catalogo = catalogo_mod.padrao()  # noqa: SLF001
    chamadas = _contar_chamadas(fontes)

    inicio_total = time.perf_counter()
    linhas = []
    for posicao, bruto in enumerate(itens, start=args.inicio + 1):
        item = {"id": f"bench-{posicao}", "numero": posicao,
                "codigo": bruto.get("codigo"), "descricao": bruto["descricao"],
                "unidade": bruto.get("unidade"),
                "quantidade": str(bruto.get("quantidade") or "")}
        antes = dict(chamadas)
        t0 = time.perf_counter()
        resultado = execucao.pesquisar_item(item, fontes, filtros={})
        dt = time.perf_counter() - t0
        est = resultado.estimativa
        na_cesta = len(est.cesta.selecionadas) if est else 0
        linhas.append({
            "numero": posicao,
            "descricao": bruto["descricao"][:60],
            "segundos": round(dt, 2),
            "encontradas": resultado.encontradas,
            "na_cesta": na_cesta,
            "status": (est.status if est else ("ERRO" if resultado.erro else
                                               "SEM_ESTIMATIVA")),
            "metodo": est.metodo if est else None,
            "valor": str(est.valor_unitario) if est and est.valor_unitario
            is not None else None,
            "mediana": str(est.estatisticas.mediana) if est and est.estatisticas
            else None,
            # análise crítica pendente (média provisória); ausente no código
            # anterior a 15/10/2026, por isso o getattr
            "pendencias": list(getattr(est, "pendencias", []) or []) if est
            else [],
            "valor_planilha": bruto.get("valor_unitario"),
            "erro_de_fonte": bool(resultado.erro),
            "chamadas": {k: chamadas.get(k, 0) - antes.get(k, 0)
                         for k in chamadas},
        })
        print(f"[{posicao:3d}] {dt:5.1f}s enc={resultado.encontradas:4d} "
              f"cesta={na_cesta:3d} {linhas[-1]['status']:<11} "
              f"{linhas[-1]['valor'] or '-':>10} | {bruto['descricao'][:45]}",
              flush=True)
    total = time.perf_counter() - inicio_total

    tempos = [linha["segundos"] for linha in linhas]
    n = len(linhas)
    resumo = {
        "quando": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "itens": n,
        "total_s": round(total, 1),
        "p50_s": _percentil(tempos, 0.5),
        "p95_s": _percentil(tempos, 0.95),
        "itens_por_minuto": round(n / (total / 60), 2) if total else None,
        "cobertura_bruta_media": round(
            statistics.mean(x["encontradas"] for x in linhas), 1) if n else 0,
        "itens_com_referencia": sum(1 for x in linhas if x["encontradas"]),
        "itens_3_mais_na_cesta": sum(1 for x in linhas if x["na_cesta"] >= 3),
        "itens_concluidos": sum(1 for x in linhas if x["status"] == "CONCLUIDO"),
        "itens_concluidos_sem_pendencia": sum(
            1 for x in linhas if x["status"] == "CONCLUIDO" and not x["pendencias"]),
        "itens_concluidos_provisorios": sum(
            1 for x in linhas if x["status"] == "CONCLUIDO" and x["pendencias"]),
        "itens_com_erro_de_fonte": sum(1 for x in linhas if x["erro_de_fonte"]),
        "metodos": {m: sum(1 for x in linhas if x["metodo"] == m)
                    for m in {x["metodo"] for x in linhas}},
        "chamadas_total": dict(chamadas),
        "chamadas_por_item": {k: round(v / n, 2) for k, v in chamadas.items()}
        if n else {},
    }
    print(json.dumps(resumo, ensure_ascii=False, indent=2))
    if args.saida:
        destino = RAIZ / args.saida
        destino.parent.mkdir(parents=True, exist_ok=True)
        destino.write_text(json.dumps({"resumo": resumo, "itens": linhas},
                                      ensure_ascii=False, indent=2),
                           encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
