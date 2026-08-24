#!/usr/bin/env bash
set -Eeuo pipefail

readonly TARGET_USER="xxxxx"
readonly REPO_HTTPS="https://github.com/madebycli/nix-config.git"
readonly REPO_SSH="git@github.com:madebycli/nix-config.git"
readonly CACHE_URL="https://attic.xuyh0120.win/lantian"
readonly CACHE_KEY="lantian:EeAUQ+W+6r7EtwnmYjeVwx5kOGEBpjlBfPlzGlTNvHc="

usage() {
  cat <<'USAGE'
Usage:
  nix-refresh              all Flake inputs and personal profile packages
  nix-refresh base         Nixpkgs, CachyOS kernel, and profile packages
  nix-refresh packages     Nixpkgs and profile packages
  nix-refresh kernel       CachyOS kernel only
  nix-refresh desktop      Home Manager, Mango, Noctalia, Greeter, Hyprland, and Caelestia
  nix-refresh profiles     personal Nix profile packages only
USAGE
}

MODE="${1:-all}"
case "$MODE" in
  all)
    INPUTS=(nixpkgs home-manager nix-cachyos-kernel mango noctalia noctalia-greeter hyprland caelestia-shell)
    UPDATE_PROFILE=1
    ;;
  base)
    INPUTS=(nixpkgs nix-cachyos-kernel)
    UPDATE_PROFILE=1
    ;;
  packages)
    INPUTS=(nixpkgs)
    UPDATE_PROFILE=1
    ;;
  kernel)
    INPUTS=(nix-cachyos-kernel)
    UPDATE_PROFILE=0
    ;;
  desktop)
    INPUTS=(home-manager mango noctalia noctalia-greeter hyprland caelestia-shell)
    UPDATE_PROFILE=0
    ;;
  profiles)
    INPUTS=()
    UPDATE_PROFILE=1
    ;;
  --help|-h|help)
    usage
    exit 0
    ;;
  *)
    usage
    printf '\nError: unknown mode: %s\n' "$MODE" >&2
    exit 2
    ;;
esac

(($# <= 1)) || { usage; printf '\nError: too many arguments.\n' >&2; exit 2; }
[[ "$EUID" -ne 0 ]] || { printf 'Error: do not run as root; sudo is used internally.\n' >&2; exit 1; }
[[ "$(id -un)" == "$TARGET_USER" ]] || { printf 'Error: run as user %s.\n' "$TARGET_USER" >&2; exit 1; }

if [[ "$MODE" == profiles ]]; then
  nix profile upgrade --all --refresh
  exit 0
fi

case "$(hostname -s)" in
  nyx|aether) HOST="$(hostname -s)" ;;
  *) printf 'Error: hostname must be nyx or aether.\n' >&2; exit 1 ;;
esac

readonly REPO="$HOME/$HOST"
[[ -d "$REPO/.git" && -f "$REPO/flake.nix" && -f "$REPO/flake.lock" ]] || {
  printf 'Error: complete repository not found: %s\n' "$REPO" >&2
  exit 1
}

REMOTE="$(git -C "$REPO" remote get-url origin)"
[[ "$REMOTE" == "$REPO_HTTPS" || "$REMOTE" == "$REPO_SSH" ]] || {
  printf 'Error: unexpected Git remote: %s\n' "$REMOTE" >&2
  exit 1
}

if ! git -C "$REPO" diff --cached --quiet; then
  printf 'Error: staged Git changes found.\n' >&2
  exit 1
fi

PROFILE="$HOST"
while IFS= read -r state_file; do
  [[ -f "$state_file" ]] || continue
  state_repo="$(jq -r '.repository // empty' "$state_file" 2>/dev/null || true)"
  [[ "$state_repo" == "$REPO" ]] || continue
  candidate="$(jq -r '.profile // empty' "$state_file" 2>/dev/null || true)"
  case "$candidate" in
    "$HOST"|"$HOST-mango"|"$HOST-niri"|"$HOST-hyprland"|"$HOST-hyprland-caelestia"|"$HOST-mango-niri"|"$HOST-mango-hyprland"|"$HOST-niri-hyprland"|"$HOST-all") PROFILE="$candidate" ;;
  esac
  break
done < <(find "$HOME/.local/state/nixos-config" -name state.json -type f 2>/dev/null || true)
readonly PROFILE

git -C "$REPO" fetch --prune origin
BRANCH="$(git -C "$REPO" branch --show-current)"
[[ -n "$BRANCH" ]] || { printf 'Error: no local branch is checked out.\n' >&2; exit 1; }
UPSTREAM="origin/$BRANCH"
git -C "$REPO" show-ref --verify --quiet "refs/remotes/$UPSTREAM" || {
  printf 'Error: upstream not found: %s\n' "$UPSTREAM" >&2
  exit 1
}
read -r AHEAD BEHIND < <(git -C "$REPO" rev-list --left-right --count "HEAD...$UPSTREAM")

if ((AHEAD > 0 && BEHIND > 0)); then
  printf 'Error: local and remote histories diverged.\n' >&2
  exit 1
fi
if ((BEHIND > 0)); then
  printf 'Error: GitHub contains newer configuration commits. Run config-update first.\n' >&2
  exit 1
fi

PUBLISH=1
((AHEAD == 0)) || PUBLISH=0
[[ -n "$(git -C "$REPO" config user.name || true)" ]] || PUBLISH=0
[[ -n "$(git -C "$REPO" config user.email || true)" ]] || PUBLISH=0

STAMP="$(date '+%Y-%m-%d_%H-%M-%S')"
BACKUP_DIR="$HOME/.local/state/nixos-config/nix-refresh-backups/$STAMP"
mkdir -p "$BACKUP_DIR"
cp -a "$REPO/flake.lock" "$BACKUP_DIR/flake.lock"

UPDATE_STARTED=0
SYSTEM_ACTIVE=0
PROFILE_UPDATE_FAILED=0
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
    printf 'Update failed; flake.lock restored from %s.\n' "$BACKUP_DIR/flake.lock" >&2
  fi
  exit "$status"
}
trap cleanup EXIT INT TERM

sudo -v
(
  while sleep 45; do
    sudo -n true 2>/dev/null || exit 0
  done
) &
SUDO_KEEPALIVE_PID=$!

printf 'Mode: %s\n' "$MODE"
printf 'Inputs:'
for input in "${INPUTS[@]}"; do printf ' %s' "$input"; done
printf '\n'

UPDATE_STARTED=1
nix flake update "${INPUTS[@]}" --flake "$REPO" --refresh

if ! git -C "$REPO" diff --quiet -- flake.lock; then
  git -C "$REPO" --no-pager diff --stat -- flake.lock
fi

CACHE_OPTIONS=(
  --option extra-substituters "$CACHE_URL"
  --option extra-trusted-public-keys "$CACHE_KEY"
)

sudo nixos-rebuild build --flake "$REPO#$PROFILE" "${CACHE_OPTIONS[@]}"
sudo nixos-rebuild switch --flake "$REPO#$PROFILE" "${CACHE_OPTIONS[@]}"
SYSTEM_ACTIVE=1

sudo install -d -m 0755 /var/lib/nixos-config
sudo touch /var/lib/nixos-config/fstrim-pending

if ((UPDATE_PROFILE == 1)); then
  if ! nix profile upgrade --all --refresh; then
    PROFILE_UPDATE_FAILED=1
    printf 'Profile update failed.\n' >&2
  fi
fi

if ! git -C "$REPO" diff --quiet -- flake.lock; then
  if ((PUBLISH == 1)); then
    git -C "$REPO" add -- flake.lock
    if git -C "$REPO" commit -m "update($MODE): refresh Flake inputs"; then
      git -C "$REPO" fetch --prune origin
      read -r PUSH_AHEAD PUSH_BEHIND < <(git -C "$REPO" rev-list --left-right --count "HEAD...$UPSTREAM")
      if ((PUSH_BEHIND == 0)); then
        git -C "$REPO" push origin "$BRANCH" || printf 'Git push failed; commit remains local.\n' >&2
      else
        printf 'Remote advanced; commit remains local.\n' >&2
      fi
    else
      git -C "$REPO" reset -q HEAD -- flake.lock || true
      printf 'Lock-file commit failed.\n' >&2
    fi
  else
    printf 'flake.lock remains modified locally.\n' >&2
  fi
fi

printf 'Profile: %s\n' "$PROFILE"

if ((PROFILE_UPDATE_FAILED == 1)); then
  exit 1
fi
