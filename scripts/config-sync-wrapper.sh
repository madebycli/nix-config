#!/usr/bin/env bash
set -Eeuo pipefail

AUTH_BACKEND="${1:?GitHub auth backend missing}"
SYNC_BACKEND="${2:?Config sync backend missing}"
shift 2
ARGS=("$@")

REPO=""
COMMAND=""
OFFLINE=0
for ((i=0; i<${#ARGS[@]}; i++)); do
  case "${ARGS[$i]}" in
    --repo)
      i=$((i+1))
      REPO="${ARGS[$i]:-}"
      ;;
    --offline)
      OFFLINE=1
      ;;
    status|push|pull|sync|init|history|doctor)
      [[ -n "$COMMAND" ]] || COMMAND="${ARGS[$i]}"
      ;;
  esac
done

find_repo() {
  local p
  for p in "$REPO" "${NIXOS_CONFIG_REPO:-}" "$PWD" "$HOME/$(hostname -s)" "$HOME/nyx" "$HOME/aether"; do
    [[ -n "$p" ]] || continue
    if [[ -d "$p/.git" && -f "$p/flake.nix" ]]; then
      (cd "$p" && pwd)
      return
    fi
  done
  return 1
}

REPO="$(find_repo)" || exec python3 "$SYNC_BACKEND" "${ARGS[@]}"

# Upload and combined synchronization are authenticated GitHub operations.
# GitHub CLI owns the browser login and credential storage; Git continues to
# perform the local transactional work (diff/add/commit/ff-only/push).
if ((OFFLINE == 0)) && [[ "$COMMAND" == push || "$COMMAND" == sync ]]; then
  python3 "$AUTH_BACKEND" prepare --repo "$REPO" --require-push
fi

exec python3 "$SYNC_BACKEND" "${ARGS[@]}"
