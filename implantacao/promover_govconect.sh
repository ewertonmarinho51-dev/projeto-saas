#!/usr/bin/env bash
# ###########################################################
#  Promover o Gov Conect 2.0 (web, api, worker) por SHA, no VPS
#
#      sudo ./promover_govconect.sh sha-0123456789ab staging
#      sudo ./promover_govconect.sh --atual
#
#  As imagens vêm PRONTAS do GHCR (workflow `govconect-imagens.yml`): o
#  host tem 1 vCPU e não constrói nada. O Streamlit (`app`) e o Caddy não
#  são tocados: este script só sobe `redis`, `api`, `worker` e `web`.
#
#  Ordem, e por quê:
#    1. baixa as TRÊS imagens antes de mexer em qualquer coisa — tag
#       errada ou registro fora do ar param aqui, com o serviço intacto;
#    2. grava as referências novas (guardando as anteriores);
#    3. sobe e espera `api` e `web` ficarem healthy;
#    4. não ficaram em 120 s: volta às referências anteriores e sai com
#       erro. Rollback de código não pede rollback de banco (nenhuma
#       migração desta frente é destrutiva).
#
#  Registro privado: `docker login ghcr.io` uma vez, com um token de
#  leitura de pacotes (RUNBOOK_P06.md). O token não passa por aqui.
# ###########################################################
set -euo pipefail

COMPOSE_DIR="${COMPOSE_DIR:-/opt/govdocs/implantacao}"
ESTADO="${ESTADO:-/etc/govdocs/govconect-imagens.env}"
REGISTRO="${REGISTRO:-ghcr.io/ewertonmarinho51-dev}"
LOG="${LOG:-/var/log/govconect-promocoes.log}"

compose() {
  # As referências entram como variáveis de interpolação do compose.
  ( set -a; [ -f "$ESTADO" ] && . "$ESTADO"; set +a
    cd "$COMPOSE_DIR" && docker compose --profile govconect "$@" )
}

if [[ "${1:-}" == "--atual" ]]; then
  [ -f "$ESTADO" ] && cat "$ESTADO" || echo "nenhuma promoção registrada ($ESTADO)"
  exit 0
fi

TAG="${1:-}"
AMBIENTE="${2:-}"
if ! [[ "$TAG" =~ ^sha-[0-9a-f]{12}$ ]] || ! [[ "$AMBIENTE" =~ ^(staging|production)$ ]]; then
  echo "uso: $0 sha-<12 hex> <staging|production>" >&2
  echo "     $0 --atual" >&2
  exit 2
fi

API="$REGISTRO/govconect-api:$TAG"
WORKER="$REGISTRO/govconect-worker:$TAG"
WEB="$REGISTRO/govconect-web:$AMBIENTE-$TAG"

echo "baixando imagens de $TAG ($AMBIENTE)..."
for imagem in "$API" "$WORKER" "$WEB"; do
  docker pull -q "$imagem" >/dev/null || { echo "ERRO: não consegui baixar $imagem; nada foi alterado." >&2; exit 1; }
done

ANTERIOR=""
[ -f "$ESTADO" ] && ANTERIOR="$(cat "$ESTADO")"
temporario="$(mktemp "$ESTADO.XXXXXX")"
printf 'GOVCONECT_IMAGEM_API=%s\nGOVCONECT_IMAGEM_WORKER=%s\nGOVCONECT_IMAGEM_WEB=%s\n' \
  "$API" "$WORKER" "$WEB" > "$temporario"
chmod 600 "$temporario"
[ -n "$ANTERIOR" ] && printf '%s\n' "$ANTERIOR" > "$ESTADO.anterior"
mv "$temporario" "$ESTADO"

saudavel() {
  local id
  id="$(compose ps -q "$1")"
  [ -n "$id" ] && [ "$(docker inspect -f '{{.State.Health.Status}}' "$id" 2>/dev/null)" = healthy ]
}

echo "subindo redis, api, worker e web..."
compose up -d --no-build redis api worker web

for _ in $(seq 1 60); do
  if saudavel api && saudavel web; then
    echo "$(date -u +%FT%TZ) $TAG $AMBIENTE ok" >> "$LOG"
    echo "promovido: $TAG ($AMBIENTE)"
    exit 0
  fi
  sleep 2
done

echo "ERRO: api/web não ficaram healthy em 120 s; voltando à versão anterior." >&2
if [ -n "$ANTERIOR" ]; then
  printf '%s\n' "$ANTERIOR" > "$ESTADO"
  compose up -d --no-build redis api worker web || true
else
  # Primeira promoção: não há para onde voltar; os serviços novos param,
  # o Streamlit segue no ar.
  rm -f "$ESTADO"
  compose stop api worker web || true
fi
echo "$(date -u +%FT%TZ) $TAG $AMBIENTE FALHOU, revertido" >> "$LOG"
exit 1
