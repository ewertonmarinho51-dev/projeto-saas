"""
Job de bancada do índice do PNCP (piloto: Pará) — limitado e retomável.

    # medição local, sem banco: o índice fica num arquivo JSON
    python scripts/indexar_pncp.py rodar --uf PA --arquivo D:/indice_pa.json \
        --dias 30 --max-chamadas 300 --max-contratacoes 80
    python scripts/indexar_pncp.py buscar --arquivo D:/indice_pa.json \
        --termos "cimento portland" "papel sulfite a4"
    python scripts/indexar_pncp.py resumo --arquivo D:/indice_pa.json

    # no banco (0042 aplicada), com a credencial de SERVIDOR no ambiente
    SUPABASE_URL=... SUPABASE_SERVICE_KEY=... \
        python scripts/indexar_pncp.py rodar --uf PA --banco --max-chamadas 500

    # agendado (serviço `indexador-pncp` do compose, perfil `indexador`):
    # uma rodada por UF a cada INDEXADOR_INTERVALO_S, orçamento separado
    # para descoberta e coleta
    python scripts/indexar_pncp.py ciclo --banco --ufs PA

`rodar` faz a descoberta (contratações atualizadas na janela) e depois a
coleta (itens e resultados homologados das pendentes), parando quando o
orçamento de chamadas acaba. Rodar de novo CONTINUA: a página da descoberta
e o último item lido de cada contratação ficam no índice.

Nada aqui liga a fonte: isso é a flag `price_source_pncp_indice`. A
credencial vem do ambiente e nunca é impressa.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from collections import Counter
from datetime import date, datetime, timezone
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
if str(RAIZ) not in sys.path:
    sys.path.insert(0, str(RAIZ))

from src.precos import pncp_indice as indice  # noqa: E402
from src.precos.fontes import Consulta  # noqa: E402


# O armazém do banco e o ciclo agendado moram em `src/` (a imagem de
# produção não carrega `scripts/`); este arquivo é a linha de comando.
from src.precos.pncp_indice_servico import (  # noqa: E402
    ArmazemSupabase, argumentos_do_ciclo, armazem_do_banco, ciclo, rodada, rodar_ciclo)

__all__ = ["ArmazemSupabase", "ciclo", "rodada"]


def _armazem(args):
    if args.banco:
        return armazem_do_banco()
    if not args.arquivo:
        raise SystemExit("informe --arquivo (índice local) ou --banco")
    return indice.ArmazemEmMemoria(args.arquivo)


def resumo(armazem: indice.ArmazemEmMemoria) -> dict:
    """Contagens do índice local: o que entrou, de onde, e o que falta."""
    estados = Counter(c.get("estado") for c in armazem.contratacoes.values())
    por_plataforma = Counter(r.get("plataforma") or "(sem nome)"
                             for r in armazem.resultados.values())
    de_fora = [r for r in armazem.resultados.values()
               if r.get("plataforma") != indice.PLATAFORMA_COMPRAS_GOV]
    return {
        "contratacoes_por_estado": dict(estados),
        "resultados_validos": len(armazem.resultados),
        "de_origem_distinta_do_compras_gov": len(de_fora),
        "com_id_de_compra_do_compras_gov": sum(
            1 for r in armazem.resultados.values() if r.get("id_compra_origem")),
        "municipios": len({(r.get("municipio"), r.get("uf"))
                           for r in armazem.resultados.values()}),
        "orgaos": len({r.get("orgao_cnpj") for r in armazem.resultados.values()}),
        "por_plataforma": dict(por_plataforma.most_common()),
        "cursores": armazem.cursores,
    }


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description="Índice do PNCP — job de bancada")
    sub = p.add_subparsers(dest="acao", required=True)
    for nome in ("rodar", "buscar", "resumo", "ciclo"):
        s = sub.add_parser(nome)
        s.add_argument("--arquivo", type=Path)
        s.add_argument("--banco", action="store_true")
        if nome == "ciclo":
            argumentos_do_ciclo(s)
        if nome == "rodar":
            s.add_argument("--uf", default="PA")
            s.add_argument("--dias", type=int, default=30)
            s.add_argument("--ate", type=date.fromisoformat, default=None)
            s.add_argument("--modalidades", type=int, nargs="*",
                           default=list(indice.MODALIDADES_PADRAO))
            s.add_argument("--max-chamadas", type=int, default=200)
            s.add_argument("--max-contratacoes", type=int, default=50)
            s.add_argument("--pausa", type=float, default=0.2)
            s.add_argument("--incluir-compras-gov", action="store_true")
        if nome == "buscar":
            s.add_argument("--termos", nargs="+", required=True)
            s.add_argument("--uf", default=None)
            s.add_argument("--limite", type=int, default=10)
    a = p.parse_args(argv)
    armazem = _armazem(a)

    if a.acao == "ciclo":
        return rodar_ciclo(a, armazem)

    if a.acao == "rodar":
        coletor = indice.Coletor(armazem, max_chamadas=a.max_chamadas,
                                 pausa_s=a.pausa,
                                 incluir_compras_gov=a.incluir_compras_gov)
        try:
            coletor.descobrir(a.uf, modalidades=a.modalidades, ate=a.ate,
                              dias=a.dias)
            if not coletor.rodada.interrompida:
                coletor.coletar(a.max_contratacoes)
        finally:
            if isinstance(armazem, indice.ArmazemEmMemoria):
                armazem.persistir()
        print(json.dumps(coletor.rodada.para_registro(), ensure_ascii=False,
                         indent=1))
        return 0

    if a.acao == "buscar":
        fonte = indice.PNCPIndice(armazem.buscar)
        for termo in a.termos:
            achado = fonte.pesquisar(Consulta(descricao=termo, uf=a.uf,
                                              limite=a.limite))
            print(f"\n== {termo}: {len(achado.referencias)} referência(s)"
                  f" | {achado.desfecho.value}")
            for r in achado.referencias[:a.limite]:
                print(f"  R$ {r.valor_unitario_original} / {r.unidade_original}"
                      f" | {r.descricao_original[:70]} | {r.orgao} ({r.uf})"
                      f" | {r.data_resultado} | {r.bruto['indice']['plataforma']}"
                      f" | {r.referencia_externa}")
        return 0

    if not isinstance(armazem, indice.ArmazemEmMemoria):
        raise SystemExit("`resumo` lê o índice local; no banco, consulte as "
                         "tabelas precos_pncp_*")
    print(json.dumps(resumo(armazem), ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
