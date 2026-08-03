#!/usr/bin/env bash
set -Eeuo pipefail

readonly TARGET_USER="xxxxx"
readonly REPO_HTTPS="https://github.com/madebycli/nix-config.git"
readonly REPO_SSH="git@github.com:madebycli/nix-config.git"
readonly CACHE_URL="https://attic.xuyh0120.win/lantian"
readonly CACHE_KEY="lantian:EeAUQ+W+6r7EtwnmYjeVwx5kOGEBpjlBfPlzGlTNvHc="

case "$(hostname -s)" in
  nyx|aether) HOST="$(hostname -s)" ;;
  *) HOST="" ;;
esac
MODE="both"
AUTO_YES=0

while (($#)); do
  case "$1" in
    --nyx) HOST="nyx" ;;
    --aether) HOST="aether" ;;
    --mango) MODE="mango" ;;
    --niri) MODE="niri" ;;
    --both) MODE="both" ;;
    --yes|-y) AUTO_YES=1 ;;
    --help|-h)
      printf 'Verwendung: config-update [--nyx|--aether] [--both|--mango|--niri] [--yes]\n'
      printf 'Ohne Hostoption wird der aktuelle Hostname verwendet.\n'
      exit 0
      ;;
    *) printf 'Fehler: unbekannte Option: %s\n' "$1" >&2; exit 2 ;;
  esac
  shift
done

[[ -n "$HOST" ]] || {
  printf 'Fehler: Host konnte nicht erkannt werden. Nutze --nyx oder --aether.\n' >&2
  exit 2
}
[[ "$EUID" -ne 0 ]] || { printf 'Fehler: nicht als root starten.\n' >&2; exit 1; }
[[ "$(id -un)" == "$TARGET_USER" ]] || { printf 'Fehler: als %s starten.\n' "$TARGET_USER" >&2; exit 1; }

case "$MODE" in
  both) PROFILE="$HOST" ;;
  mango) PROFILE="${HOST}-mango" ;;
  niri) PROFILE="${HOST}-niri" ;;
esac

REPO="$HOME/$HOST"
[[ -d "$REPO/.git" && -f "$REPO/flake.nix" ]] || { printf 'Fehler: Repository fehlt: %s\n' "$REPO" >&2; exit 1; }
REMOTE="$(git -C "$REPO" remote get-url origin)"
[[ "$REMOTE" == "$REPO_HTTPS" || "$REMOTE" == "$REPO_SSH" ]] || { printf 'Fehler: unerwartetes Remote: %s\n' "$REMOTE" >&2; exit 1; }

git -C "$REPO" fetch --prune origin
UPSTREAM="origin/$(git -C "$REPO" branch --show-current)"
read -r AHEAD BEHIND < <(git -C "$REPO" rev-list --left-right --count "HEAD...$UPSTREAM")
((AHEAD == 0 || BEHIND == 0)) || { printf 'Fehler: Git-Historie ist divergiert.\n' >&2; exit 1; }

STASHED=0
if ((BEHIND > 0)); then
  mapfile -t LOCAL < <({
    git -C "$REPO" diff --name-only
    git -C "$REPO" diff --cached --name-only
    git -C "$REPO" ls-files --others --exclude-standard
  } | sort -u)
  mapfile -t REMOTE_PATHS < <(git -C "$REPO" diff --name-only "HEAD..$UPSTREAM")

  for local_path in "${LOCAL[@]}"; do
    for remote_path in "${REMOTE_PATHS[@]}"; do
      if [[ "$local_path" == "$remote_path" || "$local_path" == "$remote_path/"* || "$remote_path" == "$local_path/"* ]]; then
        printf 'Fehler: lokale und entfernte Änderung überschneiden sich: %s / %s\n' "$local_path" "$remote_path" >&2
        exit 1
      fi
    done
  done

  if ((${#LOCAL[@]})); then
    git -C "$REPO" stash push --include-untracked -m "config-update-$(date +%s)" --quiet
    STASHED=1
  fi

  printf '\n==> Neue GitHub-Konfiguration wird übernommen\n'
  git -C "$REPO" merge --ff-only "$UPSTREAM"

  if ((STASHED)); then
    git -C "$REPO" stash pop --quiet || {
      printf 'Fehler: Wiederherstellung hatte Konflikte; die Sicherung bleibt in git stash.\n' >&2
      exit 1
    }
  fi
else
  printf '\n==> Repository ist bereits auf dem neuesten GitHub-Stand\n'
fi

CACHE_OPTIONS=(
  --option extra-substituters "$CACHE_URL"
  --option extra-trusted-public-keys "$CACHE_KEY"
)

printf '\n==> System wird gebaut: %s\n' "$PROFILE"
sudo nixos-rebuild build --flake "$REPO#$PROFILE" "${CACHE_OPTIONS[@]}"

if ((AUTO_YES == 0)); then
  printf '\nBuild erfolgreich. Aktivieren? [j/N] '
  read -r ANSWER
  case "${ANSWER,,}" in j|ja|y|yes) ;; *) exit 0 ;; esac
fi

printf '\n==> System wird aktiviert\n'
sudo nixos-rebuild switch --flake "$REPO#$PROFILE" "${CACHE_OPTIONS[@]}"

printf '\n==> TRIM wird für den nächsten Neustart vorgemerkt\n'
sudo install -d -m 0755 /var/lib/nixos-config
sudo touch /var/lib/nixos-config/fstrim-pending

printf '\nFertig. Aktiver Stand: %s#%s\n' "$REPO" "$PROFILE"
printf 'Nach dem nächsten Neustart läuft fstrim automatisch genau einmal.\n'
