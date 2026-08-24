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

MANGO=0
NIRI=0
HYPRLAND=0
ALL_DESKTOPS=0
SHELL_NAME=""
SELECTION_EXPLICIT=0
AUTO_YES=0

usage() {
  cat <<'USAGE'
Usage:
  config-update [--nyx|--aether] [desktop flags] [shell flag] [--yes]

Desktop flags can be combined:
  --mango
  --niri
  --hyprland
  --all                 Mango + Niri + Hyprland with Noctalia

Shell flags:
  --noctalia            default shell
  --caelestia-shell     only with Hyprland alone

Examples:
  config-update --niri --noctalia
  config-update --mango --niri --noctalia
  config-update --hyprland --noctalia
  config-update --hyprland --caelestia-shell
  config-update --all

Without selection flags, the last saved profile is reused. If no saved profile
exists, Mango + Noctalia is used.
USAGE
}

die() {
  printf 'Error: %s\n' "$*" >&2
  exit 1
}

select_shell() {
  local requested="$1"
  if [[ -n "$SHELL_NAME" && "$SHELL_NAME" != "$requested" ]]; then
    die "Noctalia and Caelestia Shell cannot be enabled together."
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
    --yes|-y) AUTO_YES=1 ;;
    --help|-h) usage; exit 0 ;;
    *) usage; printf '\nError: unknown option: %s\n' "$1" >&2; exit 2 ;;
  esac
  shift
done

[[ -n "$HOST" ]] || die "Host could not be detected. Use --nyx or --aether."
[[ "$EUID" -ne 0 ]] || die "Do not run as root."
[[ "$(id -un)" == "$TARGET_USER" ]] || die "Run as user $TARGET_USER."

REPO="$HOME/$HOST"
[[ -d "$REPO/.git" && -f "$REPO/flake.nix" ]] || die "Repository not found: $REPO"
REMOTE="$(git -C "$REPO" remote get-url origin)"
[[ "$REMOTE" == "$REPO_HTTPS" || "$REMOTE" == "$REPO_SSH" ]] || die "Unexpected remote: $REMOTE"

if ((SELECTION_EXPLICIT == 0)); then
  PROFILE="$HOST"
  while IFS= read -r state_file; do
    [[ -f "$state_file" ]] || continue
    state_repo="$(jq -r '.repository // empty' "$state_file" 2>/dev/null || true)"
    [[ "$state_repo" == "$REPO" ]] || continue
    candidate="$(jq -r '.profile // empty' "$state_file" 2>/dev/null || true)"
    case "$candidate" in
      "$HOST"|"$HOST-mango"|"$HOST-niri"|"$HOST-hyprland"|"$HOST-hyprland-caelestia"|"$HOST-mango-niri"|"$HOST-mango-hyprland"|"$HOST-niri-hyprland"|"$HOST-all")
        PROFILE="$candidate"
        break
        ;;
    esac
  done < <(find "$HOME/.local/state/nixos-config" -name state.json -type f 2>/dev/null || true)
else
  if ((ALL_DESKTOPS == 1)); then
    ((MANGO == 0 && NIRI == 0 && HYPRLAND == 0)) || die "Do not combine --all with individual compositor flags."
    [[ -z "$SHELL_NAME" || "$SHELL_NAME" == "noctalia" ]] || die "--all uses Noctalia as its shell."
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
    ((HYPRLAND == 1 && MANGO == 0 && NIRI == 0)) || die "Caelestia Shell is supported only with Hyprland alone."
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
fi
readonly PROFILE

git -C "$REPO" fetch --prune origin
UPSTREAM="origin/$(git -C "$REPO" branch --show-current)"
read -r AHEAD BEHIND < <(git -C "$REPO" rev-list --left-right --count "HEAD...$UPSTREAM")
((AHEAD == 0 || BEHIND == 0)) || die "Git history diverged."

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
        die "Local and remote changes overlap: $local_path / $remote_path"
      fi
    done
  done

  if ((${#LOCAL[@]})); then
    git -C "$REPO" stash push --include-untracked -m "config-update-$(date +%s)" --quiet
    STASHED=1
  fi

  printf '\n==> Applying newer GitHub configuration\n'
  git -C "$REPO" merge --ff-only "$UPSTREAM"

  if ((STASHED)); then
    git -C "$REPO" stash pop --quiet || {
      printf 'Error: restoring local changes caused conflicts; the backup remains in git stash.\n' >&2
      exit 1
    }
  fi
else
  printf '\n==> Repository is already up to date\n'
fi

CACHE_OPTIONS=(
  --option extra-substituters "$CACHE_URL"
  --option extra-trusted-public-keys "$CACHE_KEY"
)

printf '\n==> Building system profile: %s\n' "$PROFILE"
sudo nixos-rebuild build --flake "$REPO#$PROFILE" "${CACHE_OPTIONS[@]}"

if ((AUTO_YES == 0)); then
  printf '\nBuild successful. Activate? [y/N] '
  read -r ANSWER
  case "${ANSWER,,}" in y|yes|j|ja) ;; *) exit 0 ;; esac
fi

printf '\n==> Activating system\n'
sudo nixos-rebuild switch --flake "$REPO#$PROFILE" "${CACHE_OPTIONS[@]}"

printf '\n==> Scheduling TRIM for the next boot\n'
sudo install -d -m 0755 /var/lib/nixos-config
sudo touch /var/lib/nixos-config/fstrim-pending

printf '\nActive profile: %s#%s\n' "$REPO" "$PROFILE"
