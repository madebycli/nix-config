#!/usr/bin/env bash
set -Eeuo pipefail

readonly TARGET_USER="xxxxx"

usage() {
  cat <<'USAGE'
Usage:
  nix-optimize
USAGE
}

case "${1:-}" in
  "") ;;
  --help|-h|help) usage; exit 0 ;;
  *) usage; printf '\nError: nix-optimize does not accept additional arguments.\n' >&2; exit 2 ;;
esac

[[ "$EUID" -ne 0 ]] || { printf 'Error: do not run as root; sudo is used internally.\n' >&2; exit 1; }
[[ "$(id -un)" == "$TARGET_USER" ]] || { printf 'Error: run as user %s.\n' "$TARGET_USER" >&2; exit 1; }

store_bytes() {
  du -sB1 /nix/store 2>/dev/null | awk '{print $1}'
}

before="$(store_bytes)"
sudo -v
sudo nix-store --optimise -vv
after="$(store_bytes)"

saved=0
if [[ "$before" =~ ^[0-9]+$ && "$after" =~ ^[0-9]+$ && "$before" -ge "$after" ]]; then
  saved=$((before - after))
fi

printf 'Before: %s\n' "$(numfmt --to=iec-i --suffix=B "$before")"
printf 'After:  %s\n' "$(numfmt --to=iec-i --suffix=B "$after")"
printf 'Saved:  %s\n' "$(numfmt --to=iec-i --suffix=B "$saved")"
