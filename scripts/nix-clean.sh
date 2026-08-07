#!/usr/bin/env bash
set -Eeuo pipefail

readonly TARGET_USER="xxxxx"
readonly PROFILE=/nix/var/nix/profiles/system
readonly DEFAULT_BACKUPS=5

usage() {
  cat <<'USAGE'
Usage:
  nix-clean [COUNT] [--json]
  nix-clean --dry-run [COUNT] [--json]
  nix-clean list [--json]
  nix-clean --yes [COUNT]
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

json_string() {
  local value="$1"
  value="${value//\\/\\\\}"
  value="${value//\"/\\\"}"
  value="${value//$'\n'/\\n}"
  value="${value//$'\r'/\\r}"
  value="${value//$'\t'/\\t}"
  printf '"%s"' "$value"
}

emit_generation_list() {
  local json="$1" current_target boot_target link generation target status date first=1
  current_target="$(readlink -f /run/current-system 2>/dev/null || true)"
  boot_target="$(readlink -f "$PROFILE" 2>/dev/null || true)"
  if ((json == 0)); then
    printf '%-7s %-19s %s\n' 'GEN' 'DATE' 'STATUS'
    printf '%-7s %-19s %s\n' '-------' '-------------------' '------------------'
  else
    printf '{"schemaVersion":1,"generations":['
  fi
  while IFS= read -r link; do
    [[ -n "$link" ]] || continue
    generation="$(generation_number "$link")"
    target="$(readlink -f "$link" 2>/dev/null || true)"
    status="backup"
    [[ "$target" == "$boot_target" ]] && status="boot-default"
    [[ "$target" == "$current_target" ]] && status="running"
    [[ "$target" == "$current_target" && "$target" == "$boot_target" ]] && status="running-and-boot"
    date="$(stat -c '%y' "$link" 2>/dev/null | cut -d. -f1 || true)"
    if ((json == 1)); then
      ((first == 1)) || printf ','
      first=0
      printf '{"generation":%s,"createdAt":' "$generation"
      if [[ -n "$date" ]]; then json_string "$date"; else printf 'null'; fi
      printf ',"status":'
      json_string "$status"
      printf '}'
    else
      printf '%-7s %-19s %s\n' "$generation" "${date:-unknown}" "${status//-/ }"
    fi
  done < <(generation_links)
  if ((json == 1)); then printf '],"errors":[]}\n'; fi
}

DRY_RUN=0
ASSUME_YES=0
JSON=0
LIST=0
BACKUPS="$DEFAULT_BACKUPS"
number_seen=0

while (($#)); do
  case "$1" in
    list) LIST=1 ;;
    --dry-run) DRY_RUN=1 ;;
    --yes|-y) ASSUME_YES=1 ;;
    --json) JSON=1 ;;
    --help|-h|help) usage; exit 0 ;;
    [0-9]*)
      ((number_seen == 0)) || { printf 'Error: only one backup count is allowed.\n' >&2; exit 2; }
      BACKUPS="$1"
      number_seen=1
      ;;
    *) usage; printf '\nError: unknown argument: %s\n' "$1" >&2; exit 2 ;;
  esac
  shift
done

if ((LIST == 1)); then
  ((DRY_RUN == 0 && ASSUME_YES == 0 && number_seen == 0)) || { usage; exit 2; }
  emit_generation_list "$JSON"
  exit 0
fi

[[ "$BACKUPS" =~ ^([1-9]|1[0-9]|20)$ ]] || {
  printf 'Error: backup count must be between 1 and 20.\n' >&2
  exit 2
}
((JSON == 0 || DRY_RUN == 1)) || {
  printf 'Error: --json is only allowed with --dry-run or list.\n' >&2
  exit 2
}
[[ "$EUID" -ne 0 ]] || { printf 'Error: do not run as root; sudo is used internally.\n' >&2; exit 1; }
[[ "$(id -un)" == "$TARGET_USER" ]] || { printf 'Error: run as user %s.\n' "$TARGET_USER" >&2; exit 1; }
[[ -L /run/current-system && -L "$PROFILE" ]] || { printf 'Error: NixOS system profile not found.\n' >&2; exit 1; }

mapfile -t LINKS < <(generation_links)
((${#LINKS[@]} > 0)) || { printf 'Error: no system generations found.\n' >&2; exit 1; }

current_target="$(readlink -f /run/current-system)"
boot_target="$(readlink -f "$PROFILE")"
[[ "$current_target" == "$boot_target" ]] || {
  printf 'Error: running system and boot default differ.\n' >&2
  exit 1
}

current_generation=""
for link in "${LINKS[@]}"; do
  if [[ "$(readlink -f "$link")" == "$current_target" ]]; then
    current_generation="$(generation_number "$link")"
    break
  fi
done
[[ -n "$current_generation" ]] || { printf 'Error: running generation could not be resolved.\n' >&2; exit 1; }
latest_generation="$(generation_number "${LINKS[0]}")"
[[ "$current_generation" == "$latest_generation" ]] || {
  printf 'Error: running generation %s is not the latest generation %s.\n' "$current_generation" "$latest_generation" >&2
  exit 1
}

keep_total=$((BACKUPS + 1))
DELETE=()
for ((index=keep_total; index<${#LINKS[@]}; index++)); do
  DELETE+=("$(generation_number "${LINKS[$index]}")")
done

if ((JSON == 1)); then
  printf '{"schemaVersion":1,"safe":true,"generationCount":%d,' "${#LINKS[@]}"
  printf '"currentGeneration":%s,"latestGeneration":%s,' "$current_generation" "$latest_generation"
  printf '"keepBackups":%s,"deleteGenerations":[' "$BACKUPS"
  first=1
  for generation in "${DELETE[@]}"; do
    ((first == 1)) || printf ','
    first=0
    printf '%s' "$generation"
  done
  printf '],"errors":[]}\n'
  exit 0
fi

printf 'Generations: %d\n' "${#LINKS[@]}"
printf 'Keep: current %s + %d backup(s)\n' "$current_generation" "$BACKUPS"
if ((${#DELETE[@]} == 0)); then
  printf 'Remove: none\n'
  exit 0
fi
printf 'Remove: %s\n' "${DELETE[*]}"

((DRY_RUN == 1)) && exit 0

if ((ASSUME_YES == 0)); then
  read -r -p 'Delete selected generations and run garbage collection? [y/N] ' answer
  case "$answer" in y|Y|yes|YES) ;; *) exit 0 ;; esac
fi

sudo -v
sudo nix-env --profile "$PROFILE" --delete-generations "${DELETE[@]}"
sudo /run/current-system/bin/switch-to-configuration boot
sudo nix store gc
printf 'Remaining: current %s + %d backup(s)\n' "$current_generation" "$BACKUPS"
