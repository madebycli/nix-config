#!/usr/bin/env bash
set -Eeuo pipefail

BACKEND="${1:?Backend fehlt}"
shift
ARGS=("$@")
REPO=""
SCOPE="all"
COMMAND=""

for ((i=0; i<${#ARGS[@]}; i++)); do
  case "${ARGS[$i]}" in
    --repo) i=$((i+1)); REPO="${ARGS[$i]:-}" ;;
    --scope) i=$((i+1)); SCOPE="${ARGS[$i]:-all}" ;;
    status|push|pull|sync|init|history|doctor) [[ -n "$COMMAND" ]] || COMMAND="${ARGS[$i]}" ;;
  esac
done

find_repo() {
  local p
  for p in "$REPO" "${NIXOS_CONFIG_REPO:-}" "$PWD" "$HOME/$(hostname -s)" "$HOME/nyx" "$HOME/aether"; do
    [[ -n "$p" ]] || continue
    if [[ -d "$p/.git" && -f "$p/flake.nix" ]]; then (cd "$p" && pwd); return; fi
  done
  return 1
}

in_scope() {
  case "$SCOPE" in
    all) return 0 ;;
    dotfiles) [[ "$1" == config/home/* ]] ;;
    nixos) [[ "$1" != config/home/* ]] ;;
    *) return 1 ;;
  esac
}

REPO="$(find_repo)" || exec python3 "$BACKEND" "${ARGS[@]}"

if [[ "$COMMAND" == push || "$COMMAND" == sync ]]; then
  mapfile -t STAGED < <(git -C "$REPO" diff --cached --name-only)
  if ((${#STAGED[@]})); then
    for p in "${STAGED[@]}"; do
      in_scope "$p" || { printf 'Fehler: Vorgemerkte Datei außerhalb des Bereichs: %s\n' "$p" >&2; exit 1; }
    done
    printf '\nVom vorherigen Versuch sind Dateien vorgemerkt. Nur Vormerkung entfernen? [j/N] '
    read -r answer
    case "${answer,,}" in j|ja|y|yes) git -C "$REPO" reset -q HEAD -- "${STAGED[@]}" ;; *) exit 1 ;; esac
  fi

  name="$(git -C "$REPO" config user.name || true)"
  email="$(git -C "$REPO" config user.email || true)"
  if [[ -z "$name" ]]; then
    printf 'Git-Name [xnixjoyer]: '
    read -r name
    git -C "$REPO" config user.name "${name:-xnixjoyer}"
  fi
  if [[ -z "$email" ]]; then
    printf 'Git-E-Mail: '
    read -r email
    [[ -n "$email" ]] || { printf 'Fehler: Git-E-Mail erforderlich.\n' >&2; exit 1; }
    git -C "$REPO" config user.email "$email"
  fi
fi

if [[ "$COMMAND" == push || "$COMMAND" == pull || "$COMMAND" == sync ]]; then
  git -C "$REPO" fetch --prune origin
  upstream="$(git -C "$REPO" rev-parse --abbrev-ref --symbolic-full-name '@{u}' 2>/dev/null || true)"
  [[ -n "$upstream" ]] || upstream="origin/$(git -C "$REPO" branch --show-current)"
  read -r ahead behind < <(git -C "$REPO" rev-list --left-right --count "HEAD...$upstream")
  ((ahead == 0 || behind == 0)) || { printf 'Fehler: Git-Historie divergiert.\n' >&2; exit 1; }
  if ((behind > 0)); then
    mapfile -t local_paths < <({ git -C "$REPO" diff --name-only; git -C "$REPO" ls-files --others --exclude-standard; } | sort -u)
    mapfile -t remote_paths < <(git -C "$REPO" diff --name-only "HEAD..$upstream")
    for l in "${local_paths[@]}"; do
      for r in "${remote_paths[@]}"; do
        [[ "$l" == "$r" || "$l" == "$r/"* || "$r" == "$l/"* ]] && { printf 'Fehler: Lokale und entfernte Änderung überschneiden sich: %s / %s\n' "$l" "$r" >&2; exit 1; }
      done
    done
    if ((${#local_paths[@]})); then git -C "$REPO" stash push --include-untracked -m config-sync-temp --quiet; stashed=1; else stashed=0; fi
    git -C "$REPO" merge --ff-only "$upstream"
    if ((stashed)); then git -C "$REPO" stash pop --quiet; fi
  fi
fi

mapfile -t BEFORE < <(git -C "$REPO" diff --cached --name-only)
set +e
python3 "$BACKEND" "${ARGS[@]}"
status=$?
set -e
if ((status != 0)); then
  mapfile -t AFTER < <(git -C "$REPO" diff --cached --name-only)
  for p in "${AFTER[@]}"; do
    printf '%s\n' "${BEFORE[@]}" | grep -Fxq -- "$p" || git -C "$REPO" reset -q HEAD -- "$p"
  done
fi
exit "$status"
