#!/usr/bin/env bash
set -Eeuo pipefail

readonly TARGET_USER="xxxxx"
readonly REPO_HTTPS="https://github.com/madebycli/nix-config.git"
readonly REPO_SSH="git@github.com:madebycli/nix-config.git"

usage() {
  cat <<'USAGE'
Usage:
  nix-status [--online] [--json]
USAGE
}

ONLINE=0
JSON=0
while (($#)); do
  case "$1" in
    --online) ONLINE=1 ;;
    --json) JSON=1 ;;
    --help|-h|help) usage; exit 0 ;;
    *) usage; exit 2 ;;
  esac
  shift
done

[[ "$(id -un)" == "$TARGET_USER" ]] || {
  printf 'Error: run as user %s.\n' "$TARGET_USER" >&2
  exit 1
}

errors_file="$(mktemp -t nix-status-errors.XXXXXXXX)"
trap 'rm -f "$errors_file"' EXIT INT TERM
add_error() { printf '%s\n' "$1" >>"$errors_file"; }

host="$(hostname -s)"
case "$host" in nyx|aether) ;; *) add_error "unsupported-host:$host"; host="unknown" ;; esac
repo="$HOME/$host"
profile="$host"
last_sync=""
if [[ -d "$HOME/.local/state/nixos-config" ]]; then
  while IFS= read -r state_file; do
    state_repo="$(jq -r '.repository // empty' "$state_file" 2>/dev/null || true)"
    [[ "$state_repo" == "$repo" ]] || continue
    candidate="$(jq -r '.profile // empty' "$state_file" 2>/dev/null || true)"
    case "$candidate" in "$host"|"$host-mango"|"$host-niri") profile="$candidate" ;; esac
    last_sync="$(jq -r '.last_sync // empty' "$state_file" 2>/dev/null || true)"
    break
  done < <(find "$HOME/.local/state/nixos-config" -name state.json -type f 2>/dev/null | sort || true)
fi

mapfile -t generation_links < <(
  find /nix/var/nix/profiles -maxdepth 1 -type l -name 'system-*-link' -printf '%p\n' 2>/dev/null \
    | sort -t- -k2,2nr
)
generation_count="${#generation_links[@]}"
current_target="$(readlink -f /run/current-system 2>/dev/null || true)"
current_generation=""
for link in "${generation_links[@]}"; do
  if [[ "$(readlink -f "$link" 2>/dev/null || true)" == "$current_target" ]]; then
    name="$(basename "$link")"
    current_generation="${name#system-}"
    current_generation="${current_generation%-link}"
    break
  fi
done
latest_generation=""
if ((${#generation_links[@]})); then
  name="$(basename "${generation_links[0]}")"
  latest_generation="${name#system-}"
  latest_generation="${latest_generation%-link}"
fi
[[ -n "$current_generation" ]] || add_error "current-generation-unavailable"
[[ -n "$latest_generation" ]] || add_error "latest-generation-unavailable"

store_bytes="$(du -sB1 /nix/store 2>/dev/null | awk '{print $1}' || true)"
[[ "$store_bytes" =~ ^[0-9]+$ ]] || { store_bytes=0; add_error "store-size-unavailable"; }
closure_bytes="$(nix path-info --json -S /run/current-system 2>/dev/null | jq -r 'to_entries[0].value.closureSize // 0' 2>/dev/null || true)"
[[ "$closure_bytes" =~ ^[0-9]+$ ]] || { closure_bytes=0; add_error "closure-size-unavailable"; }
read -r disk_total disk_used disk_free disk_percent_raw < <(
  df -B1 --output=size,used,avail,pcent /nix/store 2>/dev/null | tail -n 1
)
disk_total="${disk_total:-0}"
disk_used="${disk_used:-0}"
disk_free="${disk_free:-0}"
disk_percent="${disk_percent_raw%%%}"
[[ "$disk_total" =~ ^[0-9]+$ ]] || disk_total=0
[[ "$disk_used" =~ ^[0-9]+$ ]] || disk_used=0
[[ "$disk_free" =~ ^[0-9]+$ ]] || disk_free=0
[[ "$disk_percent" =~ ^[0-9]+$ ]] || disk_percent=0

repository_path="$repo"
branch=""
dirty=false
ahead=0
behind=0
if [[ -d "$repo/.git" ]]; then
  branch="$(git -C "$repo" branch --show-current 2>/dev/null || true)"
  [[ -z "$(git -C "$repo" status --porcelain 2>/dev/null || true)" ]] || dirty=true
  remote="$(git -C "$repo" remote get-url origin 2>/dev/null || true)"
  if [[ "$remote" != "$REPO_HTTPS" && "$remote" != "$REPO_SSH" ]]; then
    add_error "unexpected-remote:$remote"
  elif ((ONLINE == 1)); then
    if git -C "$repo" fetch --prune origin >/dev/null 2>&1; then
      upstream="origin/$branch"
      if [[ -n "$branch" ]] && git -C "$repo" show-ref --verify --quiet "refs/remotes/$upstream"; then
        read -r ahead behind < <(git -C "$repo" rev-list --left-right --count "HEAD...$upstream")
      else
        add_error "upstream-unavailable"
      fi
    else
      add_error "repository-fetch-failed"
    fi
  fi
else
  add_error "repository-not-found:$repo"
fi

profile_packages="$(nix profile list --json 2>/dev/null | jq 'length' 2>/dev/null || true)"
[[ "$profile_packages" =~ ^[0-9]+$ ]] || { profile_packages=0; add_error "profile-list-unavailable"; }
updated_at="$(date --iso-8601=seconds)"
errors_json="$(jq -Rsc 'split("\n") | map(select(length > 0))' "$errors_file")"

if ((JSON == 1)); then
  jq -n \
    --arg host "$host" \
    --arg profile "$profile" \
    --arg currentGeneration "$current_generation" \
    --arg latestGeneration "$latest_generation" \
    --arg repositoryPath "$repository_path" \
    --arg branch "$branch" \
    --arg lastSync "$last_sync" \
    --arg updatedAt "$updated_at" \
    --argjson generationCount "$generation_count" \
    --argjson storeBytes "$store_bytes" \
    --argjson closureBytes "$closure_bytes" \
    --argjson diskTotalBytes "$disk_total" \
    --argjson diskUsedBytes "$disk_used" \
    --argjson diskFreeBytes "$disk_free" \
    --argjson diskUsedPercent "$disk_percent" \
    --argjson dirty "$dirty" \
    --argjson ahead "$ahead" \
    --argjson behind "$behind" \
    --argjson profilePackageCount "$profile_packages" \
    --argjson errors "$errors_json" \
    '{schemaVersion:1, host:$host, profile:$profile,
      currentGeneration:($currentGeneration | if length == 0 then null else tonumber end),
      latestGeneration:($latestGeneration | if length == 0 then null else tonumber end),
      generationCount:$generationCount, storeBytes:$storeBytes, closureBytes:$closureBytes,
      diskTotalBytes:$diskTotalBytes, diskUsedBytes:$diskUsedBytes,
      diskFreeBytes:$diskFreeBytes, diskUsedPercent:$diskUsedPercent,
      repositoryPath:$repositoryPath, branch:$branch, dirty:$dirty,
      ahead:$ahead, behind:$behind, profilePackageCount:$profilePackageCount,
      lastSync:($lastSync | if length == 0 then null else . end),
      updatedAt:$updatedAt, errors:$errors}'
  exit 0
fi

store_size="$(numfmt --to=iec-i --suffix=B "$store_bytes")"
closure_size="$(numfmt --to=iec-i --suffix=B "$closure_bytes")"
disk_size="$(numfmt --to=iec-i --suffix=B "$disk_total")"
disk_used_h="$(numfmt --to=iec-i --suffix=B "$disk_used")"
disk_free_h="$(numfmt --to=iec-i --suffix=B "$disk_free")"
repo_state="${branch:-not found}"
[[ "$dirty" == false ]] || repo_state+=" · dirty"
git_relation="ahead $ahead · behind $behind"

printf '╭─ NixOS Overview ──────────────────────────────────────────────╮\n'
printf '│ %-20s %-40s │\n' 'Host' "$host"
printf '│ %-20s %-40s │\n' 'Active profile' "$profile"
printf '│ %-20s %-40s │\n' 'System generation' "${current_generation:-?} of ${latest_generation:-?}"
printf '│ %-20s %-40s │\n' 'Generations' "$generation_count"
printf '│ %-20s %-40s │\n' 'Nix Store' "$store_size"
printf '│ %-20s %-40s │\n' 'Current closure' "$closure_size"
printf '│ %-20s %-40s │\n' 'Disk' "$disk_used_h / $disk_size · free $disk_free_h ($disk_percent% used)"
printf '│ %-20s %-40s │\n' 'Repository' "$repo_state"
printf '│ %-20s %-40s │\n' 'GitHub' "$git_relation"
printf '│ %-20s %-40s │\n' 'Profile packages' "$profile_packages"
printf '╰───────────────────────────────────────────────────────────────╯\n'
