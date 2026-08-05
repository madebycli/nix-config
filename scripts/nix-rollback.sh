#!/usr/bin/env bash
set -Eeuo pipefail

readonly TARGET_USER="xxxxx"

usage() {
  cat <<'USAGE'
Usage:
  nix-rollback
USAGE
}

case "${1:-}" in
  "") ;;
  --help|-h|help) usage; exit 0 ;;
  *) usage; printf '\nError: nix-rollback does not accept additional arguments.\n' >&2; exit 2 ;;
esac

[[ "$EUID" -ne 0 ]] || { printf 'Error: do not run as root; sudo is used internally.\n' >&2; exit 1; }
[[ "$(id -un)" == "$TARGET_USER" ]] || { printf 'Error: run as user %s.\n' "$TARGET_USER" >&2; exit 1; }

sudo -v
sudo nix-env --profile /nix/var/nix/profiles/system --list-generations | tail -n 6
sudo nixos-rebuild switch --rollback
printf 'Rollback complete.\n'
