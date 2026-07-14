#!/usr/bin/env bash
set -Eeuo pipefail

readonly REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
readonly MIRROR="$REPO/config/home"
readonly PATHS_FILE="$REPO/sync/paths.conf"

for command in rsync find grep; do
  command -v "$command" >/dev/null 2>&1 || {
    printf 'Fehler: %s fehlt.\n' "$command" >&2
    exit 1
  }
done
[[ -f "$PATHS_FILE" ]] || { printf 'Fehler: %s fehlt.\n' "$PATHS_FILE" >&2; exit 1; }

copy_one() {
  local relative="$1"
  local source="$HOME/$relative"
  local target="$MIRROR/$relative"

  [[ "$relative" != /* && "$relative" != *'..'* ]] || {
    printf 'Fehler: unsicherer Pfad in paths.conf: %s\n' "$relative" >&2
    exit 1
  }

  if [[ ! -d "$source" ]]; then
    printf 'Übersprungen: %s existiert nicht.\n' "$source"
    return 0
  fi

  if find "$source" -type l -print -quit | grep -q .; then
    printf 'Fehler: %s enthält symbolische Links.\n' "$source" >&2
    exit 1
  fi

  if find "$source" -type f \( \
      -name '.env' -o -name '.env.*' -o -name '*.pem' -o -name '*.key' -o \
      -name 'id_rsa' -o -name 'id_ed25519' -o -iname '*token*' -o \
      -iname '*secret*' -o -iname '*password*' \
    \) -print -quit | grep -q .; then
    printf 'Fehler: mögliche Secret-Datei unter %s gefunden.\n' "$source" >&2
    exit 1
  fi

  mkdir -p "$target"
  rsync -a \
    --exclude '.gitkeep' \
    --exclude '.env' \
    --exclude '.env.*' \
    --exclude '*.pem' \
    --exclude '*.key' \
    --exclude '*.tmp' \
    --exclude '*.lock' \
    --exclude '*.log' \
    --exclude '*~' \
    --exclude 'cache/' \
    --exclude 'Cache/' \
    --exclude 'logs/' \
    --exclude 'session/' \
    --exclude 'sessions/' \
    "$source/" "$target/"

  printf 'Übernommen: %s -> %s\n' "$source" "$target"
}

while IFS= read -r line || [[ -n "$line" ]]; do
  line="${line%%#*}"
  line="$(printf '%s' "$line" | xargs)"
  [[ -n "$line" ]] || continue
  copy_one "$line"
done < "$PATHS_FILE"

printf '\nEs wurde nichts committed oder hochgeladen.\n'
if [[ -d "$REPO/.git" ]]; then
  git -C "$REPO" status --short -- config/home 2>/dev/null || true
else
  printf 'Repository ist noch nicht mit Git initialisiert. Das ist für diesen Kopiervorgang in Ordnung.\n'
fi
