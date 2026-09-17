#!/usr/bin/env python3
"""
Roda a prova CORRESPONDENTE ao arquivo editado. Roda como PostToolUse.

A suíte inteira leva ~2,5 min. Rodá-la a cada edição seria o gancho que
bloqueia o desenvolvimento sem justificativa — o agente esperaria dois
minutos e meio para saber que mudou um comentário. Este gancho roda UM
arquivo de teste, o que casa com o módulo tocado, e só quando ele existe.

FALHA ABERTA, e mais ainda que o gancho de segredo: ele SEMPRE devolve
zero. Teste vermelho aqui é informação para o agente, não veto — quem
decide se a mudança está pronta é a suíte no `pytest -q` e no CI, que
rodam tudo. Um gancho que reprova pela metade do sinal treina a ignorar
o sinal inteiro.

O mapeamento é deliberadamente burro: `src/precos/aplicacao.py` procura
`tests/test_precos_aplicacao.py` e `tests/test_aplicacao.py`, nesta
ordem. Sem heurística de similaridade, sem rodar "o mais parecido". Ou
existe o arquivo com o nome certo, ou o gancho se cala — porque rodar o
teste ERRADO e dizer "verde" é pior que não rodar nada.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent.parent
TESTES = RAIZ / "tests"

# Teto de tempo. Se um arquivo de teste sozinho passar disto, ele não
# serve para retorno imediato e o lugar dele é a suíte.
SEGUNDOS = 90

FERRAMENTAS_DE_ESCRITA = ("Write", "Edit", "MultiEdit")


def candidatos(caminho: str) -> list[Path]:
    """Nomes de teste plausíveis para o arquivo editado, do mais específico."""
    try:
        relativo = Path(caminho).resolve().relative_to(RAIZ)
    except ValueError:
        return []

    partes = relativo.with_suffix("").parts
    if not partes or partes[0] != "src":
        return []

    miolo = partes[1:]
    if not miolo:
        return []

    nomes = []
    if len(miolo) > 1:
        nomes.append("test_" + "_".join(miolo) + ".py")
    nomes.append(f"test_{miolo[-1]}.py")

    vistos, saida = set(), []
    for nome in nomes:
        alvo = TESTES / nome
        if nome not in vistos and alvo.exists():
            vistos.add(nome)
            saida.append(alvo)
    return saida


def main() -> int:
    try:
        entrada = json.load(sys.stdin)
    except Exception:  # noqa: BLE001
        return 0

    if entrada.get("tool_name") not in FERRAMENTAS_DE_ESCRITA:
        return 0

    dados = entrada.get("tool_input") or {}
    caminho = dados.get("file_path") if isinstance(dados, dict) else None
    if not isinstance(caminho, str) or not caminho.endswith(".py"):
        return 0

    alvos = candidatos(caminho)
    if not alvos:
        return 0

    python = os.environ.get("GOVDOCS_PYTHON") or sys.executable
    try:
        resultado = subprocess.run(  # noqa: S603
            [python, "-m", "pytest", "-q", "--no-header", *map(str, alvos)],
            cwd=RAIZ, capture_output=True, text=True, timeout=SEGUNDOS,
        )
    except Exception as erro:  # noqa: BLE001
        # Inclusive o timeout. O gancho some, a suíte continua sendo a
        # autoridade.
        print(f"provas relacionadas não rodaram ({type(erro).__name__})",
              file=sys.stderr)
        return 0

    resumo = (resultado.stdout or "").strip().splitlines()
    ultima = resumo[-1] if resumo else ""
    quais = ", ".join(a.name for a in alvos)

    if resultado.returncode == 0:
        print(f"provas relacionadas ({quais}): {ultima}")
        return 0

    print(
        f"provas relacionadas ({quais}) FALHARAM: {ultima}\n"
        f"{(resultado.stdout or '')[-2000:]}",
        file=sys.stderr,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
