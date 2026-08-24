#!/usr/bin/env bash
set -Eeuo pipefail

readonly REPO_URL="https://github.com/madebycli/nix-config.git"
readonly REPO_SSH="git@github.com:madebycli/nix-config.git"
readonly SOURCE_HARDWARE="/etc/nixos/hardware-configuration.nix"
readonly TARGET_USER="xxxxx"
readonly CACHYOS_CACHE_URL="https://attic.xuyh0120.win/lantian"
readonly CACHYOS_CACHE_KEY="lantian:EeAUQ+W+6r7EtwnmYjeVwx5kOGEBpjlBfPlzGlTNvHc="

HOST=""
MANGO=0
NIRI=0
HYPRLAND=0
ALL_DESKTOPS=0
SHELL_NAME=""
SELECTION_EXPLICIT=0
AUTO_YES=0
USE_SSH=0

usage() {
  cat <<'USAGE'
Neuinstallation nach einer normalen NixOS-Grundinstallation:
  nix run github:madebycli/nix-config#install -- --nyx
  nix run github:madebycli/nix-config#install -- --aether

Desktop-Auswahl (kombinierbar):
  --mango              Mango aktivieren
  --niri               Niri aktivieren
  --hyprland           Hyprland aktivieren
  --all                Mango + Niri + Hyprland mit Noctalia

Shell-Auswahl:
  --noctalia           Noctalia verwenden (Standard)
  --caelestia-shell    Caelestia Shell verwenden; nur mit Hyprland allein

Beispiele:
  --niri --noctalia
  --mango --niri --noctalia
  --hyprland --noctalia
  --hyprland --caelestia-shell
  --all

Ohne Desktop-/Shell-Option wird Mango + Noctalia verwendet.

Weitere Optionen:
  --nyx                Host nyx
  --aether             Host aether
  --ssh                Repository über SSH klonen
  --yes, -y            Bestätigungen automatisch bejahen
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

select_shell() {
  local requested="$1"
  if [[ -n "$SHELL_NAME" && "$SHELL_NAME" != "$requested" ]]; then
    die "Noctalia und Caelestia Shell können nicht gleichzeitig aktiviert werden."
  fi
  SHELL_NAME="$requested"
  SELECTION_EXPLICIT=1
}

while (($#)); do
  case "$1" in
    --nyx) HOST="nyx" ;;
    --aether) HOST="aether" ;;
    --mango) MANGO=1; SELECTION_EXPLICIT=1 ;;
    --niri) NIRI=1; SELECTION_EXPLICIT=1 ;;
    --hyprland) HYPRLAND=1; SELECTION_EXPLICIT=1 ;;
    --all) ALL_DESKTOPS=1; SELECTION_EXPLICIT=1 ;;
    --noctalia) select_shell noctalia ;;
    --caelestia-shell) select_shell caelestia ;;
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

if ((ALL_DESKTOPS == 1)); then
  ((MANGO == 0 && NIRI == 0 && HYPRLAND == 0)) || die "--all nicht mit einzelnen Desktop-Flags kombinieren."
  [[ -z "$SHELL_NAME" || "$SHELL_NAME" == "noctalia" ]] || die "--all verwendet Noctalia als Shell."
  MANGO=1
  NIRI=1
  HYPRLAND=1
  SHELL_NAME="noctalia"
else
  if ((MANGO == 0 && NIRI == 0 && HYPRLAND == 0)); then
    MANGO=1
  fi
  [[ -n "$SHELL_NAME" ]] || SHELL_NAME="noctalia"
fi

if [[ "$SHELL_NAME" == "caelestia" ]]; then
  ((HYPRLAND == 1 && MANGO == 0 && NIRI == 0)) \
    || die "Caelestia Shell ist nur mit --hyprland allein unterstützt."
fi

if [[ "$SHELL_NAME" == "caelestia" ]]; then
  PROFILE="${HOST}-hyprland-caelestia"
elif ((MANGO == 1 && NIRI == 1 && HYPRLAND == 1)); then
  PROFILE="${HOST}-all"
elif ((MANGO == 1 && NIRI == 1)); then
  PROFILE="${HOST}-mango-niri"
elif ((MANGO == 1 && HYPRLAND == 1)); then
  PROFILE="${HOST}-mango-hyprland"
elif ((NIRI == 1 && HYPRLAND == 1)); then
  PROFILE="${HOST}-niri-hyprland"
elif ((HYPRLAND == 1)); then
  PROFILE="${HOST}-hyprland"
elif ((NIRI == 1)); then
  PROFILE="${HOST}-niri"
else
  PROFILE="$HOST"
fi
readonly PROFILE

readonly TARGET_HOME="$(getent passwd "$TARGET_USER" | cut -d: -f6)"
[[ -n "$TARGET_HOME" && -d "$TARGET_HOME" ]] || die "Home-Verzeichnis nicht gefunden: $TARGET_USER"
readonly REPO_DIR="${TARGET_HOME}/${HOST}"
readonly HOST_DIR="${REPO_DIR}/hosts/${HOST}"
readonly TARGET_HARDWARE="${HOST_DIR}/hardware-configuration.nix"
readonly HARDWARE_RELATIVE="hosts/${HOST}/hardware-configuration.nix"
readonly TIMESTAMP="$(date '+%Y-%m-%d_%H-%M-%S')"
readonly BACKUP_DIR="${TARGET_HOME}/.local/state/nixos-config/install-backups/${TIMESTAMP}"

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

# The hardware file stays local to each machine. Nix reads it as a tracked Flake
# file, while normal Git and sync operations leave the local copy untouched.
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

info "TRIM wird für den nächsten Neustart vorgemerkt"
sudo install -d -m 0755 /var/lib/nixos-config
sudo touch /var/lib/nixos-config/fstrim-pending

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
printf '\nBeim nächsten Neustart läuft fstrim automatisch genau einmal.\n'
printf '\nNächste Prüfung:\n  config-sync --repo %q status\n' "$REPO_DIR"
