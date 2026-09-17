#!/usr/bin/env bash
#
# Mantém o índice do Cartographer em dia sem reindexar o projeto inteiro.
#
# QUANDO RODAR: depois de um merge, depois de trocar de branch, ou quando
# o agente avisar que o índice está velho. NÃO entra no caminho crítico
# de nada que o usuário do aplicativo faça — o Cartographer é ferramenta
# de quem desenvolve, e o app não sabe que ele existe.
#
# POR QUE INCREMENTAL: `cartographer index .` reprocessa 232 arquivos.
# `update-index` reprocessa um. Num merge que toca cinco arquivos, a
# diferença é entre um segundo e meio e alguns milissegundos — e é o que
# torna razoável rodar isto num hook.
#
#   ./scripts/cartographer_atualizar.sh               # desde o último merge
#   ./scripts/cartographer_atualizar.sh origin/main   # desde outra ref
#   ./scripts/cartographer_atualizar.sh --completo    # reindexa tudo
#
set -euo pipefail

cd "$(dirname "$0")/.."

if ! command -v cartographer >/dev/null 2>&1; then
  # Ausência do Cartographer NÃO é erro: ele é opcional, e quem não o
  # instalou continua desenvolvendo normalmente. Sair com 0 é o que
  # permite chamar isto de um hook sem travar o commit de ninguém.
  echo "Cartographer não está instalado — nada a atualizar."
  echo "Para instalar, veja docs/cartographer.md."
  exit 0
fi

# Sem índice, incremental não tem o que atualizar: faz o primeiro.
if [ ! -f .cartographer/index.db ]; then
  echo "Sem índice ainda. Indexando o projeto pela primeira vez…"
  cartographer index .
  exit 0
fi

if [ "${1:-}" = "--completo" ]; then
  echo "Reindexando o projeto inteiro…"
  cartographer index .
  exit 0
fi

# A atribuição é em duas linhas de propósito. `${1:-HEAD@{1}}` parece
# certo e não é: o bash fecha a expansão na primeira `}` desbalanceada,
# o padrão vira `HEAD@{1` e sobra um `}` literal grudado no valor. O
# efeito era silencioso e perverso — toda execução caía no reindex
# completo, que é exatamente o que este script existe para evitar.
REF="${1:-}"
[ -n "$REF" ] || REF='HEAD@{1}'
if ! git rev-parse --verify --quiet "$REF" >/dev/null; then
  echo "Referência '$REF' não existe neste repositório."
  echo "Reindexando o projeto inteiro, que é o que sobra sem um ponto de partida."
  cartographer index .
  exit 0
fi

# `--diff-filter=d` exclui os apagados: eles saem do grafo por outro
# comando, e mandar `update-index` num arquivo que não existe mais só
# produziria erro.
MUDADOS=$(git diff --name-only --diff-filter=d "$REF" HEAD -- '*.py' '*.sql' '*.js' '*.md' || true)
APAGADOS=$(git diff --name-only --diff-filter=D "$REF" HEAD -- '*.py' '*.sql' '*.js' '*.md' || true)

if [ -z "$MUDADOS" ] && [ -z "$APAGADOS" ]; then
  echo "Nenhum arquivo indexável mudou desde $REF. Índice já está em dia."
  exit 0
fi

# O incremental pode falhar, e falha na v0.1.0 do Cartographer:
# `update_file_in_graph` passa um dicionário vazio como `stats` e
# `_process_entity` faz `stats["nodes"] += 1` — KeyError em todo arquivo
# (graph/builder.py:238). Quando isso acontece, cair para a reindexação
# completa mantém o índice CORRETO, que é o que importa; o incremental é
# otimização, não requisito. O projeto inteiro leva ~1,5s.
#
# Quando o bug for corrigido lá em cima, este caminho volta a ser usado
# sozinho e o fallback deixa de disparar — sem precisar mexer aqui.
FALHOU=0
for arquivo in $MUDADOS; do
  [ -f "$arquivo" ] || continue
  echo "  atualizando $arquivo"
  if ! cartographer update-index "$arquivo" >/dev/null 2>&1; then
    FALHOU=1
    break
  fi
done

if [ "$FALHOU" = "1" ]; then
  echo "  atualização incremental indisponível nesta versão do Cartographer."
  echo "  Reindexando o projeto inteiro (leva poucos segundos)…"
  cartographer index .
  exit 0
fi

for arquivo in $APAGADOS; do
  echo "  removendo $arquivo do grafo"
  cartographer delete-file "$arquivo" >/dev/null 2>&1 || true
done

echo "Índice atualizado."
cartographer status | head -4
