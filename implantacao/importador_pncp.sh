#!/usr/bin/env bash
# ###########################################################
#  Importador nacional do PNCP (fila durável da 0045), no VPS
#
#      sudo ./importador_pncp.sh subir              # imagem do worker no ar
#      sudo ./importador_pncp.sh plano nacional-2026-11 2023-01-01
#      sudo ./importador_pncp.sh status [campanha]
#      sudo ./importador_pncp.sh ritmo [minutos]   # inseridas/min por fonte, gargalo
#      sudo ./importador_pncp.sh logs [linhas]
#      sudo ./importador_pncp.sh pausar "motivo"
#      sudo ./importador_pncp.sh retomar
#      sudo ./importador_pncp.sh reconciliar <campanha> <desde> <ate>
#      sudo ./importador_pncp.sh reabrir-falhas <campanha>
#      sudo ./importador_pncp.sh voltar             # pausa e devolve o indexador antigo
#
#  Serviço contínuo num contêiner próprio (`importador-pncp`,
#  `--restart unless-stopped`): sobrevive a queda, reinício do host e
#  sessão SSH encerrada — nada depende de Terminal aberto. Usa a MESMA
#  imagem do worker em produção (`GOVCONECT_IMAGEM_WORKER`), o mesmo
#  arquivo de ambiente do indexador (`/etc/govdocs/indexador.env`, com a
#  chave de servidor; o valor nunca passa por aqui).
#
#  Um escritor só: `subir` para o `indexador-pncp` antigo antes de ligar o
#  novo (as duas leituras do PNCP sem coordenação dobrariam a carga na
#  fonte). Mesmo assim o banco garante a exclusividade por tarefa (lease
#  com token, 0045) e o líder único (`precos_pncp_liderar`).
#
#  Reverter NÃO apaga nada: `voltar` pausa a fila (o cursor fica), para o
#  importador e religa o indexador antigo na mesma imagem. Nunca use
#  --recomecar nem apague tarefas para "corrigir" falha.
# ###########################################################
set -euo pipefail

ESTADO="${ESTADO:-/etc/govdocs/govconect-imagens.env}"
AMBIENTE_ENV="${AMBIENTE_ENV:-/etc/govdocs/indexador.env}"
NOME="importador-pncp"
ANTIGO="indexador-pncp"
REQ_POR_S="${REQ_POR_S:-2}"
CAMPANHA_PADRAO="${CAMPANHA:-nacional-2026-11}"   # o serviço cria o plano de cada dia novo nela

imagem() {
  local img
  img="$(sed -n 's/^GOVCONECT_IMAGEM_WORKER=//p' "$ESTADO")"
  [ -n "$img" ] || { echo "PAROU: sem GOVCONECT_IMAGEM_WORKER em $ESTADO" >&2; exit 1; }
  echo "$img"
}

uma_vez() {  # contêiner descartável com o mesmo ambiente, para comandos curtos
  docker run --rm --env-file "$AMBIENTE_ENV" --read-only --tmpfs /tmp:size=32m \
    --memory 256m "$(imagem)" python -m src.precos.pncp_integral "$@"
}

case "${1:-}" in
  subir)
    IMG="$(imagem)"
    echo "== imagem: $IMG"
    docker pull -q "$IMG" >/dev/null
    if docker ps -a --format '{{.Names}}' | grep -qx "$ANTIGO"; then
      echo "== parando o indexador antigo ($ANTIGO) — um escritor só"
      docker stop "$ANTIGO" >/dev/null && docker rm "$ANTIGO" >/dev/null
    fi
    docker rm -f "$NOME" >/dev/null 2>&1 || true
    docker run -d --name "$NOME" --restart unless-stopped --env-file "$AMBIENTE_ENV" \
      --read-only --tmpfs /tmp:size=32m --memory 256m \
      --log-opt max-size=10m --log-opt max-file=3 \
      "$IMG" python -m src.precos.pncp_integral run --req-por-s "$REQ_POR_S" \
      --campanha "$CAMPANHA_PADRAO" >/dev/null
    sleep 20
    docker ps -a --filter "name=^${NOME}$" --format '{{.Names}} | {{.Image}} | {{.Status}}'
    docker inspect -f 'restart={{.HostConfig.RestartPolicy.Name}} memoria={{.HostConfig.Memory}} somente_leitura={{.HostConfig.ReadonlyRootfs}}' "$NOME"
    docker logs --tail 5 "$NOME" 2>&1 | cut -c1-300
    ;;
  plano)
    CAMPANHA="${2:?campanha}"; DESDE="${3:-2023-01-01}"
    uma_vez plan --campanha "$CAMPANHA" --desde "$DESDE" --fontes comprasgov_lote pncp_descoberta
    ;;
  status)
    if [ -n "${2:-}" ]; then uma_vez status --campanha "$2"; else uma_vez status; fi
    docker ps -a --filter "name=^${NOME}$" --format '{{.Names}} | {{.Image}} | {{.Status}}'
    ;;
  ritmo)       # o que a janela fez, por fonte: inseridas/min, recusas, tempos por fase
    uma_vez ritmo --minutos "${2:-30}"
    ;;
  logs)        # uma linha JSON por tarefa (persiste enquanto o contêiner existir)
    docker logs --tail "${2:-50}" "$NOME" 2>&1 | cut -c1-600
    ;;
  pausar)
    uma_vez pause --motivo "${2:?motivo}"
    ;;
  retomar)
    uma_vez resume
    ;;
  reconciliar)
    uma_vez reconcile --campanha "${2:?campanha}" --desde "${3:?desde}" --ate "${4:?ate}"
    ;;
  reabrir-falhas)
    uma_vez retry-failed --campanha "${2:?campanha}" --estados falha parcial
    ;;
  voltar)
    uma_vez pause --motivo "reversão operacional"
    docker stop "$NOME" >/dev/null 2>&1 && docker rm "$NOME" >/dev/null 2>&1 || true
    docker run -d --name "$ANTIGO" --restart unless-stopped --env-file "$AMBIENTE_ENV" \
      --read-only --tmpfs /tmp:size=32m --memory 256m "$(imagem)" \
      python -m src.precos.pncp_indice_servico ciclo --banco >/dev/null
    docker ps -a --filter "name=indexador" --format '{{.Names}} | {{.Image}} | {{.Status}}'
    ;;
  *)
    sed -n '3,12p' "$0"
    exit 2
    ;;
esac
