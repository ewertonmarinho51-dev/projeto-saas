#!/usr/bin/env python3
"""
Gancho SessionStart: sessão nova (ou retomada, ou compactada) que encontra
uma tarefa de implementação ativa recebe o checkpoint como contexto —
objetivo, critérios com a situação REAL de cada prova, bloqueio e próxima
ação — e continua dali, em vez de recomeçar. Sem tarefa ativa, não diz nada.
Falha aberta.
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent / "scripts"))


def contexto(entrada: dict) -> str:
    if os.environ.get("CLAUDE_CONTINUIDADE", "1") == "0":
        return ""
    import continuidade as c

    r = c.raiz(entrada.get("cwd"))
    estado = c.carregar(r)
    if not estado or estado.get("corrompido") or not estado.get("ativo"):
        return ""
    return ("Há uma tarefa de implementação em andamento neste repositório. "
            "Continue do checkpoint abaixo (não recomece); atualize-o com "
            "`python scripts/continuidade.py` nas transições.\n\n" + c.renderizar(r, estado))


def main() -> int:
    try:
        entrada = json.loads(sys.stdin.read() or "{}")
        texto = contexto(entrada)
    except Exception:  # noqa: BLE001 — falha aberta
        return 0
    if texto:
        print(json.dumps({"hookSpecificOutput": {"hookEventName": "SessionStart",
                                                 "additionalContext": texto}}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
