#!/usr/bin/env bash
set -Eeuo pipefail

readonly TARGET_USER="xxxxx"
readonly PROFILE=/nix/var/nix/profiles/system
readonly DEFAULT_BACKUPS=5

usage() {
  cat <<'USAGE'
Verwendung:
  nix-clean                 aktuelle Generation + 5 Backups behalten
  nix-clean ANZAHL          aktuelle Generation + 1 bis 20 Backups behalten
  nix-clean --dry-run [N]   nur anzeigen, nichts löschen
  nix-clean list            Generationen anzeigen
  nix-clean --yes [N]       ohne Rückfrage ausführen
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

list_generations() {
  local current_target boot_target link generation target status date
  current_target="$(readlink -f /run/current-system)"
  boot_target="$(readlink -f "$PROFILE")"
  printf '%-7s %-18s %s\n' 'GEN' 'DATUM' 'STATUS'
  printf '%-7s %-18s %s\n' '-------' '------------------' '------------------'
  while IFS= read -r link; do
    [[ -n "$link" ]] || continue
    generation="$(generation_number "$link")"
    target="$(readlink -f "$link")"
    status="Backup"
    [[ "$target" == "$boot_target" ]] && status="Boot-Standard"
    [[ "$target" == "$current_target" ]] && status="Läuft aktuell"
    [[ "$target" == "$current_target" && "$target" == "$boot_target" ]] && status="Aktuell + Boot"
    date="$(stat -c '%y' "$link" 2>/dev/null | cut -d. -f1 || true)"
    printf '%-7s %-18s %s\n' "$generation" "${date:-unbekannt}" "$status"
  done < <(generation_links)
}

DRY_RUN=0
ASSUME_YES=0
BACKUPS="$DEFAULT_BACKUPS"

if [[ "${1:-}" == "list" ]]; then
  [[ $# -eq 1 ]] || { usage; exit 2; }
  list_generations
  exit 0
fi

while (($#)); do
  case "$1" in
    --dry-run) DRY_RUN=1 ;;
    --yes|-y) ASSUME_YES=1 ;;
    --help|-h|help) usage; exit 0 ;;
    [0-9]*) BACKUPS="$1" ;;
    *) usage; printf '\nFehler: unbekanntes Argument: %s\n' "$1" >&2; exit 2 ;;
  esac
  shift
done

[[ "$BACKUPS" =~ ^([1-9]|1[0-9]|20)$ ]] || {
  printf 'Fehler: Die Zahl der Backups muss zwischen 1 und 20 liegen.\n' >&2
  exit 2
}
[[ "$EUID" -ne 0 ]] || { printf 'Fehler: nicht als root starten. Das Skript verwendet sudo selbst.\n' >&2; exit 1; }
[[ "$(id -un)" == "$TARGET_USER" ]] || { printf 'Fehler: als Benutzer %s starten.\n' "$TARGET_USER" >&2; exit 1; }
[[ -L /run/current-system && -L "$PROFILE" ]] || { printf 'Fehler: NixOS-Systemprofil nicht gefunden.\n' >&2; exit 1; }

mapfile -t LINKS < <(generation_links)
((${#LINKS[@]} > 0)) || { printf 'Fehler: keine Systemgenerationen gefunden.\n' >&2; exit 1; }

current_target="$(readlink -f /run/current-system)"
boot_target="$(readlink -f "$PROFILE")"
[[ "$current_target" == "$boot_target" ]] || {
  printf 'Abbruch: Laufendes System und Boot-Standard unterscheiden sich.\n' >&2
  printf 'Nach einem Rollback zuerst bewusst neu bauen/switchten oder den Zustand prüfen.\n' >&2
  exit 1
}

current_generation=""
for link in "${LINKS[@]}"; do
  if [[ "$(readlink -f "$link")" == "$current_target" ]]; then
    current_generation="$(generation_number "$link")"
    break
  fi
done
[[ -n "$current_generation" ]] || { printf 'Fehler: laufende Generation konnte nicht ermittelt werden.\n' >&2; exit 1; }
latest_generation="$(generation_number "${LINKS[0]}")"
[[ "$current_generation" == "$latest_generation" ]] || {
  printf 'Abbruch: Die laufende Generation %s ist nicht die neueste Generation %s.\n' "$current_generation" "$latest_generation" >&2
  printf 'So wird verhindert, dass ein noch getesteter neuerer Stand gelöscht wird.\n' >&2
  exit 1
}

keep_total=$((BACKUPS + 1))
DELETE=()
for ((index=keep_total; index<${#LINKS[@]}; index++)); do
  DELETE+=("$(generation_number "${LINKS[$index]}")")
done

printf '\nNixOS-Systemgenerationen: %d\n' "${#LINKS[@]}"
printf 'Geschützt: aktuelle Generation %s + %d Backup(s)\n' "$current_generation" "$BACKUPS"
if ((${#DELETE[@]} == 0)); then
  printf 'Nichts zu löschen.\n'
  exit 0
fi
printf 'Zu löschen (%d): %s\n' "${#DELETE[@]}" "${DELETE[*]}"

if ((DRY_RUN == 1)); then
  printf '\nDry Run: Es wurde nichts verändert.\n'
  exit 0
fi

if ((ASSUME_YES == 0)); then
  read -r -p $'Alte Systemgenerationen löschen und danach Garbage Collection starten? [j/N] ' answer
  case "$answer" in j|J|ja|Ja|JA|y|Y|yes|YES) ;; *) printf 'Abgebrochen.\n'; exit 0 ;; esac
fi

sudo -v
printf '\n==> Alte Systemgenerationen werden entfernt\n'
sudo nix-env --profile "$PROFILE" --delete-generations "${DELETE[@]}"
printf '\n==> Bootmenü wird aus dem laufenden System neu erzeugt\n'
sudo /run/current-system/bin/switch-to-configuration boot
printf '\n==> Unerreichbare Store-Pfade werden entfernt\n'
sudo nix store gc
printf '\nFertig. Aktuelle Generation und %d Backup(s) bleiben erhalten.\n' "$BACKUPS"
printf 'Für zusätzliche Deduplizierung kann anschließend `nix-optimize` ausgeführt werden.\n'
