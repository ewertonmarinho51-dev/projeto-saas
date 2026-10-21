#!/usr/bin/env bash
set -euo pipefail

# Instala um bundle WordCraft previamente aprovado. Este script não promove
# artefatos de QA: o próprio manifesto precisa trazer o estado operacional.
ARCHIVE="${1:-}"
EXPECTED_ARCHIVE_SHA256="${2:-}"
ROOT="${WORDCRAFT_RUNTIME_ROOT:-/opt/govdocs-wordcraft}"
ENV_FILE="${GOVDOCS_ENV_FILE:-/etc/govdocs/env}"
ORIGIN="${GOVDOCS_WORDCRAFT_ORIGIN:-https://govconect.com}"

if [[ -z "$ARCHIVE" || -z "$EXPECTED_ARCHIVE_SHA256" ]]; then
  echo "uso: $0 <wordcraft-runtime.zip> <sha256-do-zip>" >&2
  exit 2
fi
if [[ ! -f "$ARCHIVE" || ! "$EXPECTED_ARCHIVE_SHA256" =~ ^[0-9a-f]{64}$ ]]; then
  echo "ERRO: arquivo ou SHA-256 esperado inválido." >&2
  exit 1
fi

actual_archive_sha256="$(sha256sum "$ARCHIVE" | cut -d' ' -f1)"
if [[ "$actual_archive_sha256" != "$EXPECTED_ARCHIVE_SHA256" ]]; then
  echo "ERRO: SHA-256 do arquivo divergiu." >&2
  exit 1
fi

stage="$(mktemp -d "${ROOT}.stage.XXXXXX")"
trap 'rm -rf "$stage"' EXIT
unzip -q "$ARCHIVE" -d "$stage"

bundle="$stage/wordcraft"
manifest="$bundle/qa-manifest.json"
if [[ ! -f "$manifest" ]]; then
  echo "ERRO: manifesto ausente." >&2
  exit 1
fi

readarray -t inspected < <(python3 - "$bundle" <<'PY'
import hashlib, json, pathlib, re, sys
root = pathlib.Path(sys.argv[1]).resolve()
raw = (root / "qa-manifest.json").read_bytes()
manifest = json.loads(raw)
if manifest.get("status") != "GOVCONNECT_WORDCRAFT_DEPLOY_APPROVED":
    raise SystemExit("ERRO: artefato não aprovado para produção.")
files = manifest.get("files")
if not isinstance(files, list) or not 2 <= len(files) <= 100:
    raise SystemExit("ERRO: inventário inválido.")
seen = set()
for item in files:
    name = item.get("path")
    if (not isinstance(name, str) or name in seen or name.startswith("/")
            or any(part in {"", ".", ".."} for part in name.split("/"))):
        raise SystemExit("ERRO: caminho inválido no inventário.")
    seen.add(name)
    path = (root / name).resolve()
    if not path.is_relative_to(root) or not path.is_file():
        raise SystemExit("ERRO: asset ausente.")
    data = path.read_bytes()
    if len(data) != item.get("bytes") or hashlib.sha256(data).hexdigest() != item.get("sha256"):
        raise SystemExit("ERRO: asset divergiu do manifesto.")
if not (root / "notices" / "manifest.json").is_file():
    raise SystemExit("ERRO: avisos de distribuição ausentes.")
print(hashlib.sha256(raw).hexdigest())
PY
)
manifest_sha256="${inspected[0]}"

install -d -m 0755 "$ROOT"
next="$ROOT/wordcraft.next"
rm -rf "$next"
mv "$bundle" "$next"
previous="$ROOT/wordcraft.previous"
rm -rf "$previous"
if [[ -e "$ROOT/wordcraft" ]]; then mv "$ROOT/wordcraft" "$previous"; fi
mv "$next" "$ROOT/wordcraft"

tmp_env="$(mktemp "${ENV_FILE}.XXXXXX")"
trap 'rm -rf "$stage" "$tmp_env"' EXIT
if [[ -f "$ENV_FILE" ]]; then
  grep -Ev '^GOVDOCS_WORDCRAFT_(NODE|BUNDLE|MANIFEST_SHA256|ORIGIN)=' "$ENV_FILE" > "$tmp_env" || true
fi
cat >> "$tmp_env" <<EOF
GOVDOCS_WORDCRAFT_NODE=/usr/bin/node
GOVDOCS_WORDCRAFT_BUNDLE=/app/static/wordcraft
GOVDOCS_WORDCRAFT_MANIFEST_SHA256=$manifest_sha256
GOVDOCS_WORDCRAFT_ORIGIN=$ORIGIN
EOF
install -m 0600 "$tmp_env" "$ENV_FILE"

echo "OK: runtime WordCraft aprovado instalado; manifesto $manifest_sha256"
