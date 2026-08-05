#!/usr/bin/env bash
set -Eeuo pipefail

readonly TARGET_USER="xxxxx"
readonly REPO_HTTPS="https://github.com/madebycli/nix-config.git"
readonly REPO_SSH="git@github.com:madebycli/nix-config.git"

usage() {
  cat <<'USAGE'
Usage:
  nix-updates [all|base|packages|kernel|desktop|profiles] [--full]
USAGE
}

MODE=all
FULL=0
mode_seen=0
for argument in "$@"; do
  case "$argument" in
    --full) FULL=1 ;;
    --help|-h|help) usage; exit 0 ;;
    all|base|packages|kernel|desktop|profiles)
      ((mode_seen == 0)) || { printf 'Error: only one mode is allowed.\n' >&2; exit 2; }
      MODE="$argument"
      mode_seen=1
      ;;
    *) usage; printf '\nError: unknown argument: %s\n' "$argument" >&2; exit 2 ;;
  esac
done

case "$MODE" in
  all) INPUTS=(nixpkgs home-manager nix-cachyos-kernel mango noctalia noctalia-greeter); CHECK_PROFILE=1 ;;
  base) INPUTS=(nixpkgs nix-cachyos-kernel); CHECK_PROFILE=1 ;;
  packages) INPUTS=(nixpkgs); CHECK_PROFILE=1 ;;
  kernel) INPUTS=(nix-cachyos-kernel); CHECK_PROFILE=0 ;;
  desktop) INPUTS=(home-manager mango noctalia noctalia-greeter); CHECK_PROFILE=0 ;;
  profiles) INPUTS=(); CHECK_PROFILE=1 ;;
esac

[[ "$(id -un)" == "$TARGET_USER" ]] || {
  printf 'Error: run as user %s.\n' "$TARGET_USER" >&2
  exit 1
}

host="$(hostname -s)"
case "$host" in nyx|aether) ;; *) printf 'Error: hostname must be nyx or aether.\n' >&2; exit 1 ;; esac
repo="$HOME/$host"
profile="$host"
while IFS= read -r state_file; do
  [[ -f "$state_file" ]] || continue
  state_repo="$(jq -r '.repository // empty' "$state_file" 2>/dev/null || true)"
  [[ "$state_repo" == "$repo" ]] || continue
  candidate="$(jq -r '.profile // empty' "$state_file" 2>/dev/null || true)"
  case "$candidate" in "$host"|"$host-mango"|"$host-niri") profile="$candidate" ;; esac
  break
done < <(find "$HOME/.local/state/nixos-config" -name state.json -type f 2>/dev/null || true)

temp_root="$(mktemp -d -t nix-updates.XXXXXXXX)"
trap 'rm -rf "$temp_root"' EXIT INT TERM

if [[ "$MODE" != profiles ]]; then
  [[ -d "$repo/.git" && -f "$repo/flake.nix" && -f "$repo/flake.lock" ]] || {
    printf 'Error: complete repository not found: %s\n' "$repo" >&2
    exit 1
  }
  remote="$(git -C "$repo" remote get-url origin)"
  [[ "$remote" == "$REPO_HTTPS" || "$remote" == "$REPO_SSH" ]] || {
    printf 'Error: unexpected Git remote: %s\n' "$remote" >&2
    exit 1
  }

  git -C "$repo" fetch --prune origin
  branch="$(git -C "$repo" branch --show-current)"
  read -r ahead behind < <(git -C "$repo" rev-list --left-right --count "HEAD...origin/$branch")
  printf 'Repository: ahead %s · behind %s\n' "$ahead" "$behind"

  temp_repo="$temp_root/repo"
  cp -a "$repo" "$temp_repo"
  rm -rf "$temp_repo/.git"

  update_log="$temp_root/flake-update.log"
  if ! nix flake update "${INPUTS[@]}" --flake "$temp_repo" --refresh >"$update_log" 2>&1; then
    cat "$update_log" >&2
    exit 1
  fi

  node_for_input() {
    local lock="$1" input="$2"
    jq -r --arg input "$input" '.nodes.root.inputs[$input] | if type == "string" then . elif type == "array" then .[-1] else empty end' "$lock"
  }

  describe_input() {
    local lock="$1" input="$2" node rev stamp date_value
    node="$(node_for_input "$lock" "$input")"
    [[ -n "$node" ]] || { printf 'unknown'; return; }
    rev="$(jq -r --arg node "$node" '.nodes[$node].locked.rev // .nodes[$node].locked.narHash // "unknown"' "$lock")"
    stamp="$(jq -r --arg node "$node" '.nodes[$node].locked.lastModified // 0' "$lock")"
    if [[ "$stamp" =~ ^[1-9][0-9]*$ ]]; then
      date_value="$(date -d "@$stamp" +%Y-%m-%d 2>/dev/null || true)"
    else
      date_value=""
    fi
    [[ ${#rev} -le 12 ]] || rev="${rev:0:12}"
    if [[ -n "$date_value" ]]; then printf '%s · %s' "$date_value" "$rev"; else printf '%s' "$rev"; fi
  }

  printf '\nFlake inputs\n'
  for input in "${INPUTS[@]}"; do
    old="$(describe_input "$repo/flake.lock" "$input")"
    new="$(describe_input "$temp_repo/flake.lock" "$input")"
    if [[ "$old" == "$new" ]]; then
      printf '  %-22s %s  (up to date)\n' "$input" "$old"
    else
      printf '  %-22s %s  ->  %s\n' "$input" "$old" "$new"
    fi
  done

  if ((FULL == 1)); then
    printf '\nSystem closure\n'
    new_system="$(nix build "$temp_repo#nixosConfigurations.${profile}.config.system.build.toplevel" --no-link --print-out-paths)"
    nix store diff-closures /run/current-system "$new_system"
  fi
fi

preview_profile() {
  local profile_json package_count profile_path profile_dir profile_name temp_profile_dir temp_profile before after upgrade_log

  profile_json="$(nix profile list --json)"
  package_count="$(jq 'length' <<<"$profile_json")"
  printf '\nProfile packages\n'
  if [[ "$package_count" -eq 0 ]]; then
    printf '  none\n'
    return 0
  fi

  profile_path="${XDG_STATE_HOME:-$HOME/.local/state}/nix/profiles/profile"
  if [[ ! -L "$profile_path" ]]; then
    printf '  preview unavailable\n'
    return 0
  fi

  profile_dir="$(dirname "$profile_path")"
  profile_name="$(basename "$profile_path")"
  temp_profile_dir="$temp_root/profile"
  mkdir -p "$temp_profile_dir"
  while IFS= read -r link; do
    cp -a "$link" "$temp_profile_dir/"
  done < <(find "$profile_dir" -maxdepth 1 -type l -name "${profile_name}*" -print)

  temp_profile="$temp_profile_dir/$profile_name"
  [[ -L "$temp_profile" ]] || {
    printf '  preview unavailable\n'
    return 0
  }

  before="$(readlink -f "$temp_profile")"
  upgrade_log="$temp_root/profile-upgrade.log"
  if ! nix profile upgrade --profile "$temp_profile" --all --refresh >"$upgrade_log" 2>&1; then
    cat "$upgrade_log" >&2
    return 1
  fi
  after="$(readlink -f "$temp_profile")"

  if [[ "$before" == "$after" ]]; then
    printf '  up to date\n'
  else
    nix store diff-closures "$before" "$after"
  fi
}

if ((CHECK_PROFILE == 1)); then
  preview_profile
fi
