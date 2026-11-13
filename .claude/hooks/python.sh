#!/usr/bin/env bash
# Lançador dos ganchos: acha um Python que RODA. No Windows o `python3`
# do PATH costuma ser o atalho da Microsoft Store, que não executa nada —
# medido em 13/11/2026: os ganchos `python3 ...` falhavam calados aqui.
# Ordem: venv do projeto (worktree ou checkout principal), python3,
# python, Python instalado no perfil do Windows. Sem nenhum, falha aberta.
raiz="${CLAUDE_PROJECT_DIR:-$(pwd)}"
comum="$(git -C "$raiz" rev-parse --path-format=absolute --git-common-dir 2>/dev/null)"
candidatos=(
  "$raiz/.venv311/Scripts/python.exe" "$raiz/.venv/Scripts/python.exe"
  "$raiz/.venv/bin/python" "$raiz/.venv311/bin/python"
)
if [ -n "$comum" ]; then
  principal="$(dirname "$comum")"
  candidatos+=("$principal/.venv311/Scripts/python.exe" "$principal/.venv/Scripts/python.exe"
               "$principal/.venv/bin/python")
fi
candidatos+=(python3 python)
for p in "${LOCALAPPDATA:-/nonexistent}"/Programs/Python/Python3*/python.exe; do
  candidatos+=("$p")
done
for c in "${candidatos[@]}"; do
  if command -v "$c" >/dev/null 2>&1 || [ -x "$c" ]; then
    if "$c" -c "import sys" >/dev/null 2>&1; then
      exec "$c" "$@"
    fi
  fi
done
exit 0
