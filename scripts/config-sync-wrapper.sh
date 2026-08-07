#!/usr/bin/env bash
set -Eeuo pipefail

AUTH_BACKEND="${1:?GitHub auth backend missing}"
SYNC_BACKEND="${2:?Config sync backend missing}"
shift 2
ARGS=("$@")

REPO=""
COMMAND=""
OFFLINE=0
JSON_MODE=0
for ((i=0; i<${#ARGS[@]}; i++)); do
  case "${ARGS[$i]}" in
    --repo)
      i=$((i+1))
      REPO="${ARGS[$i]:-}"
      ;;
    --offline)
      OFFLINE=1
      ;;
    --json)
      JSON_MODE=1
      ;;
    status|push|pull|sync|init|history|doctor)
      [[ -n "$COMMAND" ]] || COMMAND="${ARGS[$i]}"
      ;;
  esac
done

# The packaged JSON contract must emit JSON and nothing else on stdout. The
# Python backend still shares human-facing helpers with the CLI, and a network
# status refresh may print informational/fetch output before its final payload.
# Keep stderr untouched for diagnostics, but normalize stdout to the last valid
# JSON object so GUI clients never have to parse terminal prose.
if ((JSON_MODE == 1)) && [[ "$COMMAND" == status ]]; then
  export NIX_CONFIG_GITHUB_AUTH_BACKEND="$AUTH_BACKEND"
  python3 "$SYNC_BACKEND" "${ARGS[@]}" | python3 -c '
import json
import sys

lines = [line.strip() for line in sys.stdin.read().splitlines() if line.strip()]
for line in reversed(lines):
    try:
        payload = json.loads(line)
    except json.JSONDecodeError:
        continue
    print(json.dumps(payload, ensure_ascii=False, sort_keys=True))
    raise SystemExit(0)
raise SystemExit("config-sync status did not emit a JSON payload")
'
  exit $?
fi

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

export NIX_CONFIG_GITHUB_AUTH_BACKEND="$AUTH_BACKEND"
exec python3 "$SYNC_BACKEND" "${ARGS[@]}"
