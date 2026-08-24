#!/usr/bin/env bash
set -Eeuo pipefail

readonly TARGET_USER="xxxxx"
readonly REPO_HTTPS="https://github.com/madebycli/nix-config.git"
readonly REPO_SSH="git@github.com:madebycli/nix-config.git"

usage() {
  cat <<'USAGE'
Usage:
  nix-status
  nix-status --online
USAGE
}

ONLINE=0
case "${1:-}" in
  "") ;;
  --online) ONLINE=1 ;;
  --help|-h|help) usage; exit 0 ;;
  *) usage; exit 2 ;;
esac
(($# <= 1)) || { usage; exit 2; }

[[ "$(id -un)" == "$TARGET_USER" ]] || {
  printf 'Error: run as user %s.\n' "$TARGET_USER" >&2
  exit 1
}

host="$(hostname -s)"
case "$host" in nyx|aether) ;; *) host="unknown" ;; esac
repo="$HOME/$host"
profile="$host"
if [[ -d "$HOME/.local/state/nixos-config" ]]; then
  while IFS= read -r state_file; do
    state_repo="$(jq -r '.repository // empty' "$state_file" 2>/dev/null || true)"
    [[ "$state_repo" == "$repo" ]] || continue
    candidate="$(jq -r '.profile // empty' "$state_file" 2>/dev/null || true)"
    case "$candidate" in
      "$host"|"$host-mango"|"$host-niri"|"$host-hyprland"|"$host-hyprland-caelestia"|"$host-mango-niri"|"$host-mango-hyprland"|"$host-niri-hyprland"|"$host-all") profile="$candidate" ;;
    esac
    break
  done < <(find "$HOME/.local/state/nixos-config" -name state.json -type f 2>/dev/null || true)
fi

mapfile -t generation_links < <(
  find /nix/var/nix/profiles -maxdepth 1 -type l -name 'system-*-link' -printf '%p\n' 2>/dev/null \
    | sort -t- -k2,2nr
)
generation_count="${#generation_links[@]}"
current_target="$(readlink -f /run/current-system 2>/dev/null || true)"
current_generation="?"
for link in "${generation_links[@]}"; do
  if [[ "$(readlink -f "$link")" == "$current_target" ]]; then
    name="$(basename "$link")"
    current_generation="${name#system-}"
    current_generation="${current_generation%-link}"
    break
  fi
done
latest_generation="?"
if ((${#generation_links[@]})); then
  name="$(basename "${generation_links[0]}")"
  latest_generation="${name#system-}"
  latest_generation="${latest_generation%-link}"
fi

store_bytes="$(du -sB1 /nix/store 2>/dev/null | awk '{print $1}' || true)"
[[ "$store_bytes" =~ ^[0-9]+$ ]] || store_bytes=0
store_size="$(numfmt --to=iec-i --suffix=B "$store_bytes")"
closure_size="$(nix path-info -Sh /run/current-system 2>/dev/null | awk '{$1=""; sub(/^ /,""); print}' || true)"
[[ -n "$closure_size" ]] || closure_size="unknown"
read -r disk_size disk_used disk_free disk_percent < <(df -h --output=size,used,avail,pcent /nix/store | tail -n 1)

repo_state="not found"
git_relation="offline"
if [[ -d "$repo/.git" ]]; then
  branch="$(git -C "$repo" branch --show-current 2>/dev/null || true)"
  dirty="$(git -C "$repo" status --porcelain 2>/dev/null || true)"
  repo_state="${branch:-detached}"
  [[ -z "$dirty" ]] || repo_state+=" · dirty"
  remote="$(git -C "$repo" remote get-url origin 2>/dev/null || true)"
  if [[ "$remote" != "$REPO_HTTPS" && "$remote" != "$REPO_SSH" ]]; then
    git_relation="unexpected remote"
  elif ((ONLINE == 1)); then
    if git -C "$repo" fetch --prune origin >/dev/null 2>&1; then
      upstream="origin/${branch}"
      if git -C "$repo" show-ref --verify --quiet "refs/remotes/$upstream"; then
        read -r ahead behind < <(git -C "$repo" rev-list --left-right --count "HEAD...$upstream")
        git_relation="ahead $ahead · behind $behind"
      else
        git_relation="no upstream"
      fi
    else
      git_relation="check failed"
    fi
  fi
fi

profile_packages="$(nix profile list --json 2>/dev/null | jq 'length' 2>/dev/null || true)"
[[ "$profile_packages" =~ ^[0-9]+$ ]] || profile_packages="unknown"

printf '╭─ NixOS Overview ──────────────────────────────────────────────╮\n'
printf '│ %-20s %-40s │\n' 'Host' "$host"
printf '│ %-20s %-40s │\n' 'Active profile' "$profile"
printf '│ %-20s %-40s │\n' 'System generation' "$current_generation of $latest_generation"
printf '│ %-20s %-40s │\n' 'Generations' "$generation_count"
printf '│ %-20s %-40s │\n' 'Nix Store' "$store_size"
printf '│ %-20s %-40s │\n' 'Current closure' "$closure_size"
printf '│ %-20s %-40s │\n' 'Disk' "$disk_used / $disk_size · free $disk_free ($disk_percent used)"
printf '│ %-20s %-40s │\n' 'Repository' "$repo_state"
printf '│ %-20s %-40s │\n' 'GitHub' "$git_relation"
printf '│ %-20s %-40s │\n' 'Profile packages' "$profile_packages"
printf '╰───────────────────────────────────────────────────────────────╯\n'
