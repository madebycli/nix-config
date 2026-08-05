#!/usr/bin/env bash
set -Eeuo pipefail

readonly TARGET_USER="xxxxx"

usage() {
  cat <<'USAGE'
Verwendung:
  nix-optimize

Dedupliziert identische Dateien im Nix Store mit `nix-store --optimise -vv`.
Es werden keine Systemgenerationen oder Konfigurationsdateien gelöscht.
USAGE
}

case "${1:-}" in
  "") ;;
  --help|-h|help) usage; exit 0 ;;
  *) usage; printf '\nFehler: nix-optimize akzeptiert keine weiteren Argumente.\n' >&2; exit 2 ;;
esac

[[ "$EUID" -ne 0 ]] || { printf 'Fehler: nicht als root starten. Das Skript verwendet sudo selbst.\n' >&2; exit 1; }
[[ "$(id -un)" == "$TARGET_USER" ]] || { printf 'Fehler: als Benutzer %s starten.\n' "$TARGET_USER" >&2; exit 1; }

store_bytes() {
  du -sB1 /nix/store 2>/dev/null | awk '{print $1}'
}

before="$(store_bytes)"
printf '\n==> Nix Store wird dedupliziert\n'
sudo -v
sudo nix-store --optimise -vv
after="$(store_bytes)"

saved=0
if [[ "$before" =~ ^[0-9]+$ && "$after" =~ ^[0-9]+$ && "$before" -ge "$after" ]]; then
  saved=$((before - after))
fi

printf '\nFertig.\n'
printf 'Vorher:    %s\n' "$(numfmt --to=iec-i --suffix=B "$before")"
printf 'Nachher:   %s\n' "$(numfmt --to=iec-i --suffix=B "$after")"
printf 'Eingespart: %s\n' "$(numfmt --to=iec-i --suffix=B "$saved")"
