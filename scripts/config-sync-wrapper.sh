#!/usr/bin/env bash
set -Eeuo pipefail

BACKEND="${1:?Backend fehlt}"
shift
ARGS=("$@")
REPO=""
COMMAND=""
OFFLINE=0

for ((i=0; i<${#ARGS[@]}; i++)); do
  case "${ARGS[$i]}" in
    --repo) i=$((i+1)); REPO="${ARGS[$i]:-}" ;;
    --offline) OFFLINE=1 ;;
    status|push|pull|sync|init|history|doctor) [[ -n "$COMMAND" ]] || COMMAND="${ARGS[$i]}" ;;
  esac
done

find_repo() {
  local p="${REPO:-${NIXOS_CONFIG_REPO:-}}"
  if [[ -n "$p" && -d "$p/.git" && -f "$p/flake.nix" ]]; then (cd "$p" && pwd); return; fi
  p="$PWD"
  while [[ "$p" != / ]]; do
    if [[ -d "$p/.git" && -f "$p/flake.nix" ]]; then printf '%s\n' "$p"; return; fi
    p="$(dirname "$p")"
  done
  for p in "$HOME/$(hostname -s)" "$HOME/nyx" "$HOME/aether"; do
    if [[ -d "$p/.git" && -f "$p/flake.nix" ]]; then (cd "$p" && pwd); return; fi
  done
  return 1
}

overlap() { [[ "$1" == "$2" || "$1" == "$2/"* || "$2" == "$1/"* ]]; }

case "$COMMAND" in push|pull|sync) ;; *) exec python3 "$BACKEND" "${ARGS[@]}" ;; esac
((OFFLINE == 0)) || exec python3 "$BACKEND" "${ARGS[@]}"
REPO="$(find_repo)" || exec python3 "$BACKEND" "${ARGS[@]}"

git -C "$REPO" fetch --prune origin
UPSTREAM="$(git -C "$REPO" rev-parse --abbrev-ref --symbolic-full-name '@{u}' 2>/dev/null || true)"
[[ -n "$UPSTREAM" ]] || UPSTREAM="origin/$(git -C "$REPO" branch --show-current)"
read -r AHEAD BEHIND < <(git -C "$REPO" rev-list --left-right --count "HEAD...$UPSTREAM")
((AHEAD == 0 || BEHIND == 0)) || { echo 'Fehler: Git-Historie divergiert.' >&2; exit 1; }

STASHED=0
if ((BEHIND > 0)); then
  mapfile -t LOCAL < <({ git -C "$REPO" diff --name-only; git -C "$REPO" diff --cached --name-only; git -C "$REPO" ls-files --others --exclude-standard; } | sort -u)
  mapfile -t REMOTE < <(git -C "$REPO" diff --name-only "HEAD..$UPSTREAM")
  for l in "${LOCAL[@]}"; do
    [[ -n "$l" ]] || continue
    for r in "${REMOTE[@]}"; do
      [[ -n "$r" ]] || continue
      overlap "$l" "$r" && { printf 'Fehler: Lokal und GitHub ändern dieselbe Datei: %s\n' "$l" >&2; exit 1; }
    done
  done

  if [[ "$COMMAND" == pull && ${#LOCAL[@]} -gt 0 ]]; then
    git -C "$REPO" diff --cached --quiet || { echo 'Fehler: Vorgemerkte Änderungen vorhanden.' >&2; exit 1; }
    git -C "$REPO" stash push --include-untracked -m 'config-sync temporary pull' --quiet
    STASHED=1
  fi

  printf '\n==> Nicht überlappende GitHub-Änderungen werden übernommen\n'
  git -C "$REPO" merge --ff-only "$UPSTREAM"
fi

set +e
python3 "$BACKEND" "${ARGS[@]}"
STATUS=$?
set -e
if ((STASHED == 1)); then
  git -C "$REPO" stash pop --quiet || {
    echo 'Fehler: Lokale Änderungen liegen sicher in git stash.' >&2
    exit 1
  }
fi
exit "$STATUS"
