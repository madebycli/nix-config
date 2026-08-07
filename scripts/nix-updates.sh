#!/usr/bin/env bash
set -Eeuo pipefail

readonly TARGET_USER="xxxxx"
readonly REPO_HTTPS="https://github.com/madebycli/nix-config.git"
readonly REPO_SSH="git@github.com:madebycli/nix-config.git"

usage() {
  cat <<'USAGE'
Usage:
  nix-updates [all|base|packages|kernel|desktop|profiles] [--full] [--json]
USAGE
}

MODE=all
FULL=0
JSON=0
mode_seen=0
for argument in "$@"; do
  case "$argument" in
    --full) FULL=1 ;;
    --json) JSON=1 ;;
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
done < <(find "$HOME/.local/state/nixos-config" -name state.json -type f 2>/dev/null | sort || true)

temp_root="$(mktemp -d -t nix-updates.XXXXXXXX)"
trap 'rm -rf "$temp_root"' EXIT INT TERM
sources_file="$temp_root/sources.ndjson"
errors_file="$temp_root/errors.txt"
: >"$sources_file"
: >"$errors_file"

emit_failure() {
  local message="$1"
  printf '%s\n' "$message" >&2
  if ((JSON == 1)); then
    jq -n --arg mode "$MODE" --arg message "$message" \
      '{schemaVersion:1, mode:$mode, repositoryRelation:null, sources:[],
        profile:{packageCount:0, updateAvailable:false, summary:"not checked"},
        fullClosurePreview:null, errors:[$message]}'
  fi
  exit 1
}

display_name() {
  case "$1" in
    nixpkgs) printf 'Nixpkgs' ;;
    home-manager) printf 'Home Manager' ;;
    nix-cachyos-kernel) printf 'Kernel/Core' ;;
    mango) printf 'Mango' ;;
    noctalia) printf 'Noctalia' ;;
    noctalia-greeter) printf 'Noctalia Greeter' ;;
    *) printf '%s' "$1" ;;
  esac
}

node_for_input() {
  local lock="$1" input="$2"
  jq -r --arg input "$input" '.nodes.root.inputs[$input] | if type == "string" then . elif type == "array" then .[-1] else empty end' "$lock"
}

input_revision() {
  local lock="$1" input="$2" node
  node="$(node_for_input "$lock" "$input")"
  [[ -n "$node" ]] || { printf 'unknown'; return; }
  jq -r --arg node "$node" '.nodes[$node].locked.rev // .nodes[$node].locked.narHash // "unknown"' "$lock"
}

input_date() {
  local lock="$1" input="$2" node stamp
  node="$(node_for_input "$lock" "$input")"
  [[ -n "$node" ]] || return 0
  stamp="$(jq -r --arg node "$node" '.nodes[$node].locked.lastModified // 0' "$lock")"
  if [[ "$stamp" =~ ^[1-9][0-9]*$ ]]; then
    date -d "@$stamp" +%Y-%m-%d 2>/dev/null || true
  fi
}

short_revision() {
  local value="$1"
  if ((${#value} > 12)); then printf '%s' "${value:0:12}"; else printf '%s' "$value"; fi
}

branch=""
ahead=0
behind=0
if [[ "$MODE" != profiles ]]; then
  [[ -d "$repo/.git" && -f "$repo/flake.nix" && -f "$repo/flake.lock" ]] || \
    emit_failure "complete repository not found: $repo"
  remote="$(git -C "$repo" remote get-url origin 2>/dev/null || true)"
  [[ "$remote" == "$REPO_HTTPS" || "$remote" == "$REPO_SSH" ]] || \
    emit_failure "unexpected Git remote: $remote"

  git -C "$repo" fetch --prune origin >/dev/null 2>&1 || emit_failure "repository fetch failed"
  branch="$(git -C "$repo" branch --show-current)"
  [[ -n "$branch" ]] || emit_failure "no local branch is checked out"
  git -C "$repo" show-ref --verify --quiet "refs/remotes/origin/$branch" || \
    emit_failure "upstream not found: origin/$branch"
  read -r ahead behind < <(git -C "$repo" rev-list --left-right --count "HEAD...origin/$branch")

  temp_repo="$temp_root/repo"
  cp -a "$repo" "$temp_repo"
  rm -rf "$temp_repo/.git"

  update_log="$temp_root/flake-update.log"
  if ! NO_COLOR=1 nix flake update "${INPUTS[@]}" --flake "$temp_repo" --refresh >"$update_log" 2>&1; then
    message="$(tail -n 40 "$update_log" | sed -r 's/\x1B\[[0-9;]*[mK]//g')"
    emit_failure "flake preview failed: $message"
  fi

  if ((JSON == 0)); then
    printf 'Repository: ahead %s · behind %s\n' "$ahead" "$behind"
    printf '\nFlake inputs\n'
  fi

  for input in "${INPUTS[@]}"; do
    current_revision="$(input_revision "$repo/flake.lock" "$input")"
    candidate_revision="$(input_revision "$temp_repo/flake.lock" "$input")"
    current_date="$(input_date "$repo/flake.lock" "$input")"
    candidate_date="$(input_date "$temp_repo/flake.lock" "$input")"
    update_available=false
    status="current"
    if [[ "$current_revision" != "$candidate_revision" ]]; then
      update_available=true
      status="update-available"
    fi
    jq -n \
      --arg id "$input" \
      --arg displayName "$(display_name "$input")" \
      --arg currentRevision "$current_revision" \
      --arg candidateRevision "$candidate_revision" \
      --arg currentDate "$current_date" \
      --arg candidateDate "$candidate_date" \
      --arg status "$status" \
      --argjson updateAvailable "$update_available" \
      '{id:$id, displayName:$displayName, currentRevision:$currentRevision,
        candidateRevision:$candidateRevision,
        currentDate:($currentDate | if length == 0 then null else . end),
        candidateDate:($candidateDate | if length == 0 then null else . end),
        updateAvailable:$updateAvailable, status:$status, error:null}' >>"$sources_file"

    if ((JSON == 0)); then
      old_label="$(short_revision "$current_revision")"
      new_label="$(short_revision "$candidate_revision")"
      [[ -z "$current_date" ]] || old_label="$current_date · $old_label"
      [[ -z "$candidate_date" ]] || new_label="$candidate_date · $new_label"
      if [[ "$update_available" == false ]]; then
        printf '  %-22s %s  (up to date)\n' "$input" "$old_label"
      else
        printf '  %-22s %s  ->  %s\n' "$input" "$old_label" "$new_label"
      fi
    fi
  done
fi

profile_count=0
profile_update=false
profile_summary="not checked"
if ((CHECK_PROFILE == 1)); then
  profile_json="$(nix profile list --json 2>/dev/null)" || emit_failure "profile list failed"
  profile_count="$(jq 'length' <<<"$profile_json")"
  profile_summary="up to date"
  if ((JSON == 0)); then printf '\nProfile packages\n'; fi
  if ((profile_count == 0)); then
    profile_summary="none"
    ((JSON == 1)) || printf '  none\n'
  else
    profile_path="${XDG_STATE_HOME:-$HOME/.local/state}/nix/profiles/profile"
    if [[ ! -L "$profile_path" ]]; then
      profile_summary="preview unavailable"
      ((JSON == 1)) || printf '  preview unavailable\n'
    else
      profile_dir="$(dirname "$profile_path")"
      profile_name="$(basename "$profile_path")"
      temp_profile_dir="$temp_root/profile"
      mkdir -p "$temp_profile_dir"
      while IFS= read -r link; do cp -a "$link" "$temp_profile_dir/"; done < <(
        find "$profile_dir" -maxdepth 1 -type l -name "${profile_name}*" -print
      )
      temp_profile="$temp_profile_dir/$profile_name"
      if [[ -L "$temp_profile" ]]; then
        before="$(readlink -f "$temp_profile")"
        upgrade_log="$temp_root/profile-upgrade.log"
        if ! NO_COLOR=1 nix profile upgrade --profile "$temp_profile" --all --refresh >"$upgrade_log" 2>&1; then
          emit_failure "profile preview failed: $(tail -n 40 "$upgrade_log")"
        fi
        after="$(readlink -f "$temp_profile")"
        if [[ "$before" != "$after" ]]; then
          profile_update=true
          profile_summary="updates available"
          if ((JSON == 0)); then
            NO_COLOR=1 nix store diff-closures "$before" "$after" || true
          fi
        else
          ((JSON == 1)) || printf '  up to date\n'
        fi
      else
        profile_summary="preview unavailable"
        ((JSON == 1)) || printf '  preview unavailable\n'
      fi
    fi
  fi
fi

full_preview=""
if ((FULL == 1)) && [[ "$MODE" != profiles ]]; then
  ((JSON == 1)) || printf '\nSystem closure\n'
  new_system="$(NO_COLOR=1 nix build "$temp_repo#nixosConfigurations.${profile}.config.system.build.toplevel" --no-link --print-out-paths)" || \
    emit_failure "full closure build failed"
  full_preview="$(NO_COLOR=1 nix store diff-closures /run/current-system "$new_system" 2>&1 | sed -r 's/\x1B\[[0-9;]*[mK]//g' || true)"
  if ((JSON == 0)); then printf '%s\n' "$full_preview"; fi
fi

if ((JSON == 1)); then
  sources_json="$(jq -s '.' "$sources_file")"
  errors_json="$(jq -Rsc 'split("\n") | map(select(length > 0))' "$errors_file")"
  jq -n \
    --arg mode "$MODE" \
    --arg branch "$branch" \
    --arg profileSummary "$profile_summary" \
    --arg fullClosurePreview "$full_preview" \
    --argjson ahead "$ahead" \
    --argjson behind "$behind" \
    --argjson packageCount "$profile_count" \
    --argjson profileUpdate "$profile_update" \
    --argjson sources "$sources_json" \
    --argjson errors "$errors_json" \
    '{schemaVersion:1, mode:$mode,
      repositoryRelation:{branch:$branch, ahead:$ahead, behind:$behind},
      sources:$sources,
      profile:{packageCount:$packageCount, updateAvailable:$profileUpdate, summary:$profileSummary},
      fullClosurePreview:($fullClosurePreview | if length == 0 then null else . end),
      errors:$errors}'
fi
