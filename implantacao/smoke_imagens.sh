#!/usr/bin/env bash
# ###########################################################
#  Smoke das imagens do Gov Conect 2.0 (P06) — sem banco, sem segredo.
#
#    implantacao/smoke_imagens.sh govconect-api:ci govconect-worker:ci govconect-web:ci
#
#  O que prova, em cada imagem já construída:
#    api    — não roda como root; não tem Streamlit; liveness 200 sem
#             nada configurado; readiness 503 e rota privada recusada
#             (falha fechada, ADR-002);
#    worker — não roda como root; converte DOCX em PDF pelo LibreOffice
#             com a raiz SOMENTE LEITURA e /tmp em tmpfs (como no compose);
#    web    — não roda como root; serve /entrar.
#  Sai com código ≠ 0 no primeiro desvio.
# ###########################################################
set -euo pipefail

API="${1:?imagem da api}"
WORKER="${2:?imagem do worker}"
WEB="${3:?imagem do web}"
CONTENTORES=()

limpar() { for c in "${CONTENTORES[@]}"; do docker rm -f "$c" >/dev/null 2>&1 || true; done; }
trap limpar EXIT

falhar() { echo "FALHOU: $*" >&2; exit 1; }

esperar_http() {  # url código-esperado
  for _ in $(seq 1 40); do
    codigo="$(curl -s -o /dev/null -w '%{http_code}' "$1" || true)"
    [ "$codigo" = "$2" ] && return 0
    sleep 1
  done
  falhar "$1 respondeu ${codigo:-nada}, esperado $2"
}

uid_de() { docker run --rm --entrypoint sh "$1" -c 'id -u'; }

echo "== api"
[ "$(uid_de "$API")" != "0" ] || falhar "api roda como root"
docker run --rm --entrypoint python "$API" -c \
  "import importlib.util, sys; sys.exit(importlib.util.find_spec('streamlit') is not None)" \
  || falhar "Streamlit instalado na imagem da api"
# Editor de documentos: o dono documental valida com Node + validate.mjs.
docker run --rm --entrypoint sh "$API" -c \
  'node --version && test -f /app/assets/wordcraft_editor/validate.mjs && test -f /app/assets/wordcraft_editor/host.mjs && test -f /app/docs/wordcraft/upstream.lock.json' \
  || falhar "api sem o validador nativo do WordCraft"
CONTENTORES+=("$(docker run -d --read-only --tmpfs /tmp -e APP_ENV=test -p 127.0.0.1:18000:8000 "$API")")
esperar_http http://127.0.0.1:18000/health/live 200
esperar_http http://127.0.0.1:18000/health/ready 503
esperar_http http://127.0.0.1:18000/api/v1/me 401

echo "== worker"
[ "$(uid_de "$WORKER")" != "0" ] || falhar "worker roda como root"
docker run --rm --read-only --tmpfs /tmp:size=512m --entrypoint python "$WORKER" -c '
import io
from docx import Document
from src import export

d = Document()
d.add_paragraph("Pesquisa de preços: Caneta esferográfica azul, R$ 2,35 (média).")
buf = io.BytesIO()
d.save(buf)
pdf = export._docx_em_pdf(buf.getvalue(), tempo_limite=120)
assert pdf and pdf[:5] == b"%PDF-", "LibreOffice não converteu"
print("pdf", len(pdf), "bytes")
' || falhar "worker não gera PDF com a raiz somente leitura"

echo "== web"
[ "$(uid_de "$WEB")" != "0" ] || falhar "web roda como root"
CONTENTORES+=("$(docker run -d --read-only --tmpfs /tmp -e GOVCONECT_API_URL=http://127.0.0.1:9 \
  -p 127.0.0.1:13000:3000 "$WEB")")
esperar_http http://127.0.0.1:13000/entrar 200

echo "== tamanhos"
docker image ls --format '{{.Repository}}:{{.Tag}} {{.Size}}' | grep -E "^($(echo "$API|$WORKER|$WEB" | sed 's/[.]/\\./g')) " || true
echo "smoke das imagens: ok"
