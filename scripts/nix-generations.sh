#!/usr/bin/env bash
set -Eeuo pipefail

readonly PROFILE=/nix/var/nix/profiles/system

usage() {
  cat <<'USAGE'
Usage:
  nix-generations [--json]
  nix-generations --last COUNT [--json]
  nix-generations --diff GENERATION_A GENERATION_B
USAGE
}

generation_links() {
  find /nix/var/nix/profiles -maxdepth 1 -type l -name 'system-*-link' -printf '%p\n' 2>/dev/null \
    | sort -t- -k2,2nr
}

generation_number() {
  local name
  name="$(basename "$1")"
  name="${name#system-}"
  printf '%s\n' "${name%-link}"
}

find_generation_link() {
  local generation="$1"
  local link="/nix/var/nix/profiles/system-${generation}-link"
  [[ -L "$link" ]] || {
    printf 'Error: system generation %s does not exist.\n' "$generation" >&2
    exit 1
  }
  printf '%s\n' "$link"
}

json_string() {
  local value="$1"
  value="${value//\\/\\\\}"
  value="${value//\"/\\\"}"
  value="${value//$'\n'/\\n}"
  value="${value//$'\r'/\\r}"
  value="${value//$'\t'/\\t}"
  printf '"%s"' "$value"
}

print_list() {
  local limit="$1" json="$2"
  local current_target boot_target count=0 link generation target status date size size_bytes
  local current_generation="" latest_generation="" first=1
  mapfile -t links < <(generation_links)
  current_target="$(readlink -f /run/current-system 2>/dev/null || true)"
  boot_target="$(readlink -f "$PROFILE" 2>/dev/null || true)"
  if ((${#links[@]})); then
    latest_generation="$(generation_number "${links[0]}")"
  fi
  for link in "${links[@]}"; do
    if [[ "$(readlink -f "$link" 2>/dev/null || true)" == "$current_target" ]]; then
      current_generation="$(generation_number "$link")"
      break
    fi
  done

  if ((json == 0)); then
    printf '%-7s %-19s %-18s %s\n' 'GEN' 'DATE' 'STATUS' 'CLOSURE'
    printf '%-7s %-19s %-18s %s\n' '-------' '-------------------' '------------------' '----------'
  else
    printf '{"schemaVersion":1,"currentGeneration":'
    if [[ -n "$current_generation" ]]; then printf '%s' "$current_generation"; else printf 'null'; fi
    printf ',"latestGeneration":'
    if [[ -n "$latest_generation" ]]; then printf '%s' "$latest_generation"; else printf 'null'; fi
    printf ',"generationCount":%d,"generations":[' "${#links[@]}"
  fi

  for link in "${links[@]}"; do
    ((count += 1))
    ((limit == 0 || count <= limit)) || break
    generation="$(generation_number "$link")"
    target="$(readlink -f "$link" 2>/dev/null || true)"
    status="backup"
    [[ "$target" == "$boot_target" ]] && status="boot-default"
    [[ "$target" == "$current_target" ]] && status="running"
    [[ "$target" == "$current_target" && "$target" == "$boot_target" ]] && status="running-and-boot"
    date="$(stat -c '%y' "$link" 2>/dev/null | cut -d. -f1 || true)"
    size_bytes="$(nix path-info -S "$link" 2>/dev/null | awk 'NR == 1 {print $2}' || true)"
    [[ "$size_bytes" =~ ^[0-9]+$ ]] || size_bytes=0
    if ((json == 1)); then
      ((first == 1)) || printf ','
      first=0
      printf '{"generation":%s,"createdAt":' "$generation"
      if [[ -n "$date" ]]; then json_string "$date"; else printf 'null'; fi
      printf ',"status":'
      json_string "$status"
      printf ',"closurePath":'
      json_string "$target"
      printf ',"closureBytes":%s}' "$size_bytes"
    else
      size="$(numfmt --to=iec-i --suffix=B "$size_bytes")"
      printf '%-7s %-19s %-18s %s\n' "$generation" "${date:-unknown}" "${status//-/ }" "$size"
    fi
  done

  if ((json == 1)); then
    printf '],"errors":[]}\n'
  fi
}

JSON=0
ARGS=()
for argument in "$@"; do
  if [[ "$argument" == --json ]]; then JSON=1; else ARGS+=("$argument"); fi
done
set -- "${ARGS[@]}"

case "${1:-}" in
  "") print_list 0 "$JSON" ;;
  --help|-h|help) usage ;;
  --last)
    [[ $# -eq 2 && "$2" =~ ^[1-9][0-9]*$ ]] || { usage; exit 2; }
    print_list "$2" "$JSON"
    ;;
  --diff)
    ((JSON == 0)) || { printf 'Error: --json is not supported with --diff.\n' >&2; exit 2; }
    [[ $# -eq 3 && "$2" =~ ^[0-9]+$ && "$3" =~ ^[0-9]+$ ]] || { usage; exit 2; }
    first="$(find_generation_link "$2")"
    second="$(find_generation_link "$3")"
    nix store diff-closures "$first" "$second"
    ;;
  *) usage; exit 2 ;;
esac
