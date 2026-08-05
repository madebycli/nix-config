#!/usr/bin/env bash
set -Eeuo pipefail

readonly PROFILE=/nix/var/nix/profiles/system

usage() {
  cat <<'USAGE'
Verwendung:
  nix-generations
  nix-generations --last ANZAHL
  nix-generations --diff GENERATION_A GENERATION_B
USAGE
}

generation_links() {
  find /nix/var/nix/profiles -maxdepth 1 -type l -name 'system-*-link' -printf '%p\n' \
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
  [[ -L "$link" ]] || { printf 'Fehler: Systemgeneration %s existiert nicht.\n' "$generation" >&2; exit 1; }
  printf '%s\n' "$link"
}

print_list() {
  local limit="$1"
  local current_target boot_target count=0 link generation target status date size
  current_target="$(readlink -f /run/current-system)"
  boot_target="$(readlink -f "$PROFILE")"

  printf '%-7s %-18s %-18s %s\n' 'GEN' 'DATUM' 'STATUS' 'CLOSURE'
  printf '%-7s %-18s %-18s %s\n' '-------' '------------------' '------------------' '----------'

  while IFS= read -r link; do
    [[ -n "$link" ]] || continue
    ((count += 1))
    ((limit == 0 || count <= limit)) || break
    generation="$(generation_number "$link")"
    target="$(readlink -f "$link")"
    status="Backup"
    [[ "$target" == "$boot_target" ]] && status="Boot-Standard"
    [[ "$target" == "$current_target" ]] && status="Läuft aktuell"
    [[ "$target" == "$current_target" && "$target" == "$boot_target" ]] && status="Aktuell + Boot"
    date="$(stat -c '%y' "$link" 2>/dev/null | cut -d. -f1 || true)"
    size="$(nix path-info -Sh "$link" 2>/dev/null | awk '{$1=""; sub(/^ /,""); print}' || true)"
    [[ -n "$size" ]] || size="unbekannt"
    printf '%-7s %-18s %-18s %s\n' "$generation" "${date:-unbekannt}" "$status" "$size"
  done < <(generation_links)
}

case "${1:-}" in
  "") print_list 0 ;;
  --help|-h|help) usage ;;
  --last)
    [[ $# -eq 2 && "$2" =~ ^[1-9][0-9]*$ ]] || { usage; exit 2; }
    print_list "$2"
    ;;
  --diff)
    [[ $# -eq 3 && "$2" =~ ^[0-9]+$ && "$3" =~ ^[0-9]+$ ]] || { usage; exit 2; }
    first="$(find_generation_link "$2")"
    second="$(find_generation_link "$3")"
    printf 'Unterschiede: Generation %s -> %s\n\n' "$2" "$3"
    nix store diff-closures "$first" "$second"
    ;;
  *) usage; exit 2 ;;
esac
