#!/usr/bin/env bash
# ###########################################################
#  Promover uma versão para produção, no VPS
#
#      sudo ./promover.sh v1.4.0
#      sudo ./promover.sh --atual        # que versão está no ar?
#
#  PRODUÇÃO NÃO SEGUE `main`, e é isso que dá sentido a testar
#  antes de subir. O Streamlit Cloud acompanha `main` e recebe
#  tudo que mergeia; o VPS só se move quando alguém roda este
#  script com uma TAG. O intervalo entre os dois é a janela de
#  conferência.
# ###########################################################
set -euo pipefail

REPO="${REPO:-/opt/govdocs}"
COMPOSE_DIR="$REPO/implantacao"
DOMINIO="${DOMINIO:-govconect.com}"

cd "$REPO"

# --- que versão está no ar ------------------------------------
if [[ "${1:-}" == "--atual" ]]; then
  echo "versão no ar: $(git describe --tags --exact-match 2>/dev/null \
      || git rev-parse --short HEAD)"
  exit 0
fi

TAG="${1:-}"
if [[ -z "$TAG" ]]; then
  echo "uso: $0 <tag>            (ex.: $0 v1.4.0)" >&2
  echo "     $0 --atual" >&2
  exit 2
fi

# --- a versão anterior, para o caso de precisar voltar ---------
# Capturada ANTES de qualquer coisa: depois do checkout já é tarde,
# e "qual era mesmo a versão de ontem?" no meio de um incidente é
# uma pergunta que ninguém deveria ter que responder de memória.
ANTERIOR="$(git describe --tags --exact-match 2>/dev/null \
    || git rev-parse --short HEAD)"
echo "versão atual: $ANTERIOR"

echo "buscando tags..."
git fetch --tags --prune origin

# A tag precisa EXISTIR antes de mexer em qualquer coisa. Sem esta
# checagem, um erro de digitação derruba o serviço e só se descobre
# no `docker compose up` seguinte, com o app fora do ar.
if ! git rev-parse -q --verify "refs/tags/$TAG" >/dev/null; then
  echo "ERRO: a tag '$TAG' não existe no repositório." >&2
  echo "disponíveis (mais recentes):" >&2
  git tag --sort=-creatordate | head -10 >&2
  exit 1
fi

echo "promovendo $ANTERIOR -> $TAG"
git checkout --detach "$TAG"

cd "$COMPOSE_DIR"
docker compose up -d --build

# --- a promoção só termina quando o app RESPONDE ---------------
#
# `docker compose up` devolve o controle quando os contentores
# foram criados, não quando o aplicativo está servindo. Declarar
# sucesso ali é declarar sucesso cedo demais — e a diferença
# aparece justamente no dia em que a versão nova não sobe.
echo -n "aguardando o app responder"
for _ in $(seq 1 30); do
  if curl -fsS "https://$DOMINIO/_stcore/health" >/dev/null 2>&1; then
    echo
    echo "OK: $TAG no ar e respondendo."
    exit 0
  fi
  echo -n "."
  sleep 3
done

echo
echo "ERRO: o app não respondeu em 90s depois de subir $TAG." >&2
echo "logs:      cd $COMPOSE_DIR && docker compose logs --tail=50 app" >&2
echo "para voltar: sudo $0 $ANTERIOR" >&2
exit 1
