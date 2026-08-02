#!/usr/bin/env bash
set -Eeuo pipefail

readonly TARGET_USER="xxxxx"

usage() {
  cat <<'USAGE'
Verwendung:
  system-rollback

Wechselt das laufende System und den Boot-Standard auf die vorherige
NixOS-Systemgeneration. Die Git-Konfiguration und flake.lock werden nicht
verändert.
USAGE
}

case "${1:-}" in
  "") ;;
  --help|-h|help)
    usage
    exit 0
    ;;
  *)
    usage
    printf '\nFehler: system-rollback akzeptiert keine weiteren Argumente.\n' >&2
    exit 2
    ;;
esac

[[ "$EUID" -ne 0 ]] || {
  printf 'Fehler: nicht als root starten. Das Skript verwendet sudo selbst.\n' >&2
  exit 1
}
[[ "$(id -un)" == "$TARGET_USER" ]] || {
  printf 'Fehler: als Benutzer %s starten.\n' "$TARGET_USER" >&2
  exit 1
}

printf '\n==> Verfügbare letzte Systemgenerationen\n'
sudo nix-env \
  --profile /nix/var/nix/profiles/system \
  --list-generations \
  | tail -n 5

printf '\n==> Administratorrechte werden bestätigt\n'
sudo -v

printf '\n==> Wechsel auf die vorherige NixOS-Generation\n'
sudo nixos-rebuild switch --rollback

printf '\nRollback erfolgreich.\n'
printf 'Falls Kernel oder Initrd betroffen waren, den Rechner anschließend neu starten.\n'
