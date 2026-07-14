#!/usr/bin/env bash
set -Eeuo pipefail

readonly REPO_URL="https://github.com/xnixjoyer/nixos-config.git"
readonly REPO_SSH="git@github.com:xnixjoyer/nixos-config.git"
readonly SOURCE_HARDWARE="/etc/nixos/hardware-configuration.nix"
readonly TARGET_USER="xxxxx"
readonly CACHYOS_CACHE_URL="https://attic.xuyh0120.win/lantian"
readonly CACHYOS_CACHE_KEY="lantian:EeAUQ+W+6r7EtwnmYjeVwx5kOGEBpjlBfPlzGlTNvHc="

HOST=""
MODE="both"
AUTO_YES=0
USE_SSH=0

usage() {
  cat <<'USAGE'
Neuinstallation nach einer normalen NixOS-Grundinstallation:
  nix run github:xnixjoyer/nixos-config#install -- --nyx
  nix run github:xnixjoyer/nixos-config#install -- --aether

Optionen:
  --nyx             Host nyx
  --aether          Host aether
  --mango           nur Mango
  --niri            nur Niri
  --both            Mango und Niri (Standard)
  --ssh             Repository über SSH klonen (SSH-Key muss funktionieren)
  --yes, -y         Bestätigungen automatisch bejahen
USAGE
}

die() {
  printf '\nFehler: %s\n' "$*" >&2
  exit 1
}

info() {
  printf '\n==> %s\n' "$*"
}

confirm() {
  (( AUTO_YES == 1 )) && return 0
  printf '\n%s [j/N] ' "$1"
  read -r answer
  case "$answer" in
    j|J|ja|Ja|JA|y|Y|yes|YES) return 0 ;;
    *) return 1 ;;
  esac
}

while (($#)); do
  case "$1" in
    --nyx) HOST="nyx" ;;
    --aether) HOST="aether" ;;
    --mango) MODE="mango" ;;
    --niri) MODE="niri" ;;
    --both) MODE="both" ;;
    --ssh) USE_SSH=1 ;;
    --yes|-y) AUTO_YES=1 ;;
    --help|-h) usage; exit 0 ;;
    *) usage; die "Unbekannte Option: $1" ;;
  esac
  shift
done

[[ -n "$HOST" ]] || { usage; die "Bitte --nyx oder --aether angeben."; }
[[ "$EUID" -ne 0 ]] || die "Nicht als root starten. Das Skript verwendet sudo selbst."
[[ -e /etc/NIXOS ]] || die "Dieses System scheint kein installiertes NixOS zu sein."
[[ -f "$SOURCE_HARDWARE" ]] || die "$SOURCE_HARDWARE fehlt."
id "$TARGET_USER" >/dev/null 2>&1 || die "Der fest konfigurierte Benutzer '$TARGET_USER' existiert nicht."
[[ "$(id -un)" == "$TARGET_USER" ]] || die "Bitte als Benutzer '$TARGET_USER' starten."

for command in git nix sudo rsync; do
  command -v "$command" >/dev/null 2>&1 || die "$command fehlt."
done

readonly TARGET_HOME="$(getent passwd "$TARGET_USER" | cut -d: -f6)"
[[ -n "$TARGET_HOME" && -d "$TARGET_HOME" ]] || die "Home-Verzeichnis nicht gefunden: $TARGET_USER"
readonly REPO_DIR="${TARGET_HOME}/${HOST}"
readonly HOST_DIR="${REPO_DIR}/hosts/${HOST}"
readonly TARGET_HARDWARE="${HOST_DIR}/hardware-configuration.nix"
readonly HARDWARE_RELATIVE="hosts/${HOST}/hardware-configuration.nix"
readonly TIMESTAMP="$(date '+%Y-%m-%d_%H-%M-%S')"
readonly BACKUP_DIR="${TARGET_HOME}/.local/state/nixos-config/install-backups/${TIMESTAMP}"

case "$MODE" in
  both) PROFILE="$HOST" ;;
  mango) PROFILE="${HOST}-mango" ;;
  niri) PROFILE="${HOST}-niri" ;;
  *) die "Ungültiges Desktopprofil." ;;
esac
readonly PROFILE

if (( USE_SSH == 1 )); then
  CLONE_URL="$REPO_SSH"
else
  CLONE_URL="$REPO_URL"
fi
readonly CLONE_URL

if [[ ! -e "$REPO_DIR" ]]; then
  info "Repository wird nach $REPO_DIR geklont"
  git clone "$CLONE_URL" "$REPO_DIR"
elif [[ ! -d "$REPO_DIR/.git" ]]; then
  die "$REPO_DIR existiert, ist aber kein Git-Repository."
else
  remote_url="$(git -C "$REPO_DIR" remote get-url origin 2>/dev/null || true)"
  [[ "$remote_url" == "$REPO_URL" || "$remote_url" == "$REPO_SSH" ]] \
    || die "Unerwartetes Git-Remote: $remote_url"

  if [[ -z "$(git -C "$REPO_DIR" status --porcelain)" ]]; then
    info "Vorhandenes Repository wird per Fast-Forward aktualisiert"
    git -C "$REPO_DIR" pull --ff-only
  else
    info "Lokale Änderungen vorhanden; Git-Pull wird aus Sicherheitsgründen übersprungen"
    git -C "$REPO_DIR" status --short
  fi
fi

[[ -d "$HOST_DIR" ]] || die "Host fehlt im Repository: $HOST"
[[ -f "$HOST_DIR/default.nix" ]] || die "Hostdefinition fehlt: $HOST_DIR/default.nix"
git -C "$REPO_DIR" ls-files --error-unmatch "$HARDWARE_RELATIVE" >/dev/null 2>&1 \
  || die "Hardware-Platzhalter ist nicht durch Git erfasst: $HARDWARE_RELATIVE"

cd "$REPO_DIR"
info "Flake-Inputs werden im lokalen Clone auf den neuesten Stand aktualisiert"
nix flake update

mkdir -p "$BACKUP_DIR"
if [[ -f "$TARGET_HARDWARE" ]] && ! cmp -s "$SOURCE_HARDWARE" "$TARGET_HARDWARE"; then
  cp -a "$TARGET_HARDWARE" "$BACKUP_DIR/${HOST}-hardware-configuration.nix"
fi

info "Aktuelle lokale Hardwarekonfiguration wird für $HOST verwendet"
install -m 0644 "$SOURCE_HARDWARE" "$TARGET_HARDWARE"

# Die Hardwaredatei bleibt pro Rechner lokal. Sie wird von Nix als getrackte
# Flake-Datei gelesen, aber von normalen Git-/Sync-Vorgängen nicht verändert.
git -C "$REPO_DIR" update-index --skip-worktree "$HARDWARE_RELATIVE"

info "Flake-Ausgabe wird ausgewertet: $PROFILE"
nix eval --raw ".#nixosConfigurations.${PROFILE}.config.networking.hostName" >/dev/null

NIX_CACHE_OPTIONS=(
  --option extra-substituters "$CACHYOS_CACHE_URL"
  --option extra-trusted-public-keys "$CACHYOS_CACHE_KEY"
)

info "CachyOS-Binär-Cache wird für den ersten Build als root verwendet"
info "System wird zuerst gebaut: $PROFILE"
sudo nixos-rebuild build \
  --flake ".#${PROFILE}" \
  "${NIX_CACHE_OPTIONS[@]}"

if ! confirm "Build erfolgreich. Neue Konfiguration aktivieren?"; then
  printf '\nKein Switch durchgeführt. Build: %s/result\n' "$REPO_DIR"
  exit 0
fi

info "System wird aktiviert"
sudo nixos-rebuild switch \
  --flake ".#${PROFILE}" \
  "${NIX_CACHE_OPTIONS[@]}"

SYNC_BIN="/run/current-system/sw/bin/config-sync"
if [[ ! -x "$SYNC_BIN" ]]; then
  die "config-sync wurde nicht im neuen System gefunden: $SYNC_BIN"
fi

info "Dotconfigs werden sicher aus dem Repository initialisiert"
init_args=(
  --repo "$REPO_DIR"
  --profile "$PROFILE"
)
(( AUTO_YES == 1 )) && init_args+=(--yes)
"$SYNC_BIN" "${init_args[@]}" init --from-repo --force

printf '\nFertig.\nHost: %s\nProfil: %s\nRepository: %s\nInstallationsbackups: %s\n' \
  "$HOST" "$PROFILE" "$REPO_DIR" "$BACKUP_DIR"
printf '\nNächste Prüfung:\n  config-sync --repo %q status\n' "$REPO_DIR"
