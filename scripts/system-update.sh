#!/usr/bin/env bash
set -Eeuo pipefail

readonly TARGET_USER="xxxxx"
readonly REPO_HTTPS="https://github.com/madebycli/nix-config.git"
readonly REPO_SSH="git@github.com:madebycli/nix-config.git"
readonly CACHE_URL="https://attic.xuyh0120.win/lantian"
readonly CACHE_KEY="lantian:EeAUQ+W+6r7EtwnmYjeVwx5kOGEBpjlBfPlzGlTNvHc="

usage() {
  cat <<'USAGE'
Verwendung:
  system-update              alle Flake-Inputs inklusive Anwendungskatalog
  system-update base         Nixpkgs und CachyOS-Kernel
  system-update packages     Nixpkgs und Anwendungskatalog
  system-update kernel       nur CachyOS-Kernel
  system-update desktop      Home Manager, Mango, Noctalia und Greeter

Der Host und das zuletzt verwendete Desktopprofil werden automatisch erkannt.
Das System wird zuerst gebaut und danach ohne weitere Bestätigung aktiviert.
USAGE
}

MODE="${1:-all}"
case "$MODE" in
  all)
    INPUTS=(nixpkgs nix-pkgs home-manager nix-cachyos-kernel mango noctalia noctalia-greeter)
    ;;
  base)
    INPUTS=(nixpkgs nix-cachyos-kernel)
    ;;
  packages)
    INPUTS=(nixpkgs nix-pkgs)
    ;;
  kernel)
    INPUTS=(nix-cachyos-kernel)
    ;;
  desktop)
    INPUTS=(home-manager mango noctalia noctalia-greeter)
    ;;
  --help|-h|help)
    usage
    exit 0
    ;;
  *)
    usage
    printf '\nFehler: unbekannter Modus: %s\n' "$MODE" >&2
    exit 2
    ;;
esac

(($# <= 1)) || {
  usage
  printf '\nFehler: zu viele Argumente.\n' >&2
  exit 2
}

[[ "$EUID" -ne 0 ]] || {
  printf 'Fehler: nicht als root starten. Das Skript verwendet sudo selbst.\n' >&2
  exit 1
}
[[ "$(id -un)" == "$TARGET_USER" ]] || {
  printf 'Fehler: als Benutzer %s starten.\n' "$TARGET_USER" >&2
  exit 1
}

case "$(hostname -s)" in
  nyx|aether) HOST="$(hostname -s)" ;;
  *)
    printf 'Fehler: Hostname muss nyx oder aether sein.\n' >&2
    exit 1
    ;;
esac

readonly REPO="$HOME/$HOST"
[[ -d "$REPO/.git" && -f "$REPO/flake.nix" && -f "$REPO/flake.lock" ]] || {
  printf 'Fehler: vollständiges Repository fehlt: %s\n' "$REPO" >&2
  exit 1
}

REMOTE="$(git -C "$REPO" remote get-url origin)"
[[ "$REMOTE" == "$REPO_HTTPS" || "$REMOTE" == "$REPO_SSH" ]] || {
  printf 'Fehler: unerwartetes Git-Remote: %s\n' "$REMOTE" >&2
  exit 1
}

if ! git -C "$REPO" diff --cached --quiet; then
  printf 'Fehler: vorgemerkte Git-Änderungen vorhanden. Erst committen oder mit git reset entstagen.\n' >&2
  exit 1
fi

PROFILE="$HOST"
while IFS= read -r state_file; do
  [[ -f "$state_file" ]] || continue
  state_repo="$(jq -r '.repository // empty' "$state_file" 2>/dev/null || true)"
  [[ "$state_repo" == "$REPO" ]] || continue
  candidate="$(jq -r '.profile // empty' "$state_file" 2>/dev/null || true)"
  case "$candidate" in
    "$HOST"|"$HOST-mango"|"$HOST-niri") PROFILE="$candidate" ;;
  esac
  break
done < <(find "$HOME/.local/state/nixos-config" -name state.json -type f 2>/dev/null || true)
readonly PROFILE

printf '\n==> GitHub-Stand wird geprüft\n'
git -C "$REPO" fetch --prune origin
BRANCH="$(git -C "$REPO" branch --show-current)"
UPSTREAM="origin/$BRANCH"
read -r AHEAD BEHIND < <(git -C "$REPO" rev-list --left-right --count "HEAD...$UPSTREAM")

if ((AHEAD > 0 && BEHIND > 0)); then
  printf 'Fehler: lokale und entfernte Git-Historie sind divergiert.\n' >&2
  exit 1
fi
if ((BEHIND > 0)); then
  printf 'Fehler: GitHub enthält eine neuere Konfiguration. Zuerst config-update ausführen.\n' >&2
  exit 1
fi

PUBLISH=1
((AHEAD == 0)) || PUBLISH=0
[[ -n "$(git -C "$REPO" config user.name || true)" ]] || PUBLISH=0
[[ -n "$(git -C "$REPO" config user.email || true)" ]] || PUBLISH=0

STAMP="$(date '+%Y-%m-%d_%H-%M-%S')"
BACKUP_DIR="$HOME/.local/state/nixos-config/system-update-backups/$STAMP"
mkdir -p "$BACKUP_DIR"
cp -a "$REPO/flake.lock" "$BACKUP_DIR/flake.lock"

UPDATE_STARTED=0
SYSTEM_ACTIVE=0
SUDO_KEEPALIVE_PID=""

cleanup() {
  status=$?
  trap - EXIT INT TERM

  if [[ -n "$SUDO_KEEPALIVE_PID" ]]; then
    kill "$SUDO_KEEPALIVE_PID" 2>/dev/null || true
    wait "$SUDO_KEEPALIVE_PID" 2>/dev/null || true
  fi

  if ((status != 0 && UPDATE_STARTED == 1 && SYSTEM_ACTIVE == 0)); then
    cp -a "$BACKUP_DIR/flake.lock" "$REPO/flake.lock"
    printf '\nUpdate fehlgeschlagen. Die vorherige flake.lock wurde wiederhergestellt.\n' >&2
    printf 'Sicherung: %s\n' "$BACKUP_DIR/flake.lock" >&2
  fi

  exit "$status"
}
trap cleanup EXIT INT TERM

printf '\n==> Administratorrechte werden einmalig bestätigt\n'
sudo -v
(
  while sleep 45; do
    sudo -n true 2>/dev/null || exit 0
  done
) &
SUDO_KEEPALIVE_PID=$!

printf '\n==> Update-Modus: %s\n' "$MODE"
printf 'Inputs:'
for input in "${INPUTS[@]}"; do
  printf ' %s' "$input"
done
printf '\n'

UPDATE_STARTED=1
nix flake update "${INPUTS[@]}" --flake "$REPO" --refresh

if git -C "$REPO" diff --quiet -- flake.lock; then
  printf '\n==> flake.lock war bereits aktuell\n'
else
  printf '\n==> Änderungen der flake.lock\n'
  git -C "$REPO" --no-pager diff --stat -- flake.lock
fi

CACHE_OPTIONS=(
  --option extra-substituters "$CACHE_URL"
  --option extra-trusted-public-keys "$CACHE_KEY"
)

printf '\n==> System wird gebaut: %s\n' "$PROFILE"
sudo nixos-rebuild build \
  --flake "$REPO#$PROFILE" \
  "${CACHE_OPTIONS[@]}"

printf '\n==> Erfolgreicher Build wird aktiviert\n'
sudo nixos-rebuild switch \
  --flake "$REPO#$PROFILE" \
  "${CACHE_OPTIONS[@]}"
SYSTEM_ACTIVE=1

printf '\n==> TRIM wird für den nächsten Neustart vorgemerkt\n'
sudo install -d -m 0755 /var/lib/nixos-config
sudo touch /var/lib/nixos-config/fstrim-pending

if ! git -C "$REPO" diff --quiet -- flake.lock; then
  if ((PUBLISH == 1)); then
    printf '\n==> Aktualisierte flake.lock wird versioniert\n'
    git -C "$REPO" add -- flake.lock

    if git -C "$REPO" commit -m "update($MODE): Flake-Inputs aktualisiert"; then
      git -C "$REPO" fetch --prune origin
      read -r PUSH_AHEAD PUSH_BEHIND < <(
        git -C "$REPO" rev-list --left-right --count "HEAD...$UPSTREAM"
      )

      if ((PUSH_BEHIND == 0)); then
        if git -C "$REPO" push origin "$BRANCH"; then
          printf 'flake.lock wurde nach GitHub gepusht.\n'
        else
          printf 'Hinweis: Systemupdate erfolgreich, aber Git-Push fehlgeschlagen. Der Commit bleibt lokal.\n' >&2
        fi
      else
        printf 'Hinweis: GitHub wurde während des Updates verändert. Der Lockfile-Commit bleibt lokal.\n' >&2
      fi
    else
      git -C "$REPO" reset -q HEAD -- flake.lock || true
      printf 'Hinweis: Systemupdate erfolgreich, aber flake.lock konnte nicht committed werden.\n' >&2
    fi
  else
    printf '\nHinweis: flake.lock bleibt lokal geändert.\n'
    printf 'Automatischer Commit/Push wurde wegen fehlender Git-Identität oder lokaler Commits übersprungen.\n'
  fi
fi

printf '\nFertig.\n'
printf 'Modus: %s\nProfil: %s\nRepository: %s\n' "$MODE" "$PROFILE" "$REPO"
printf 'Nach dem nächsten Neustart läuft fstrim automatisch einmal.\n'
