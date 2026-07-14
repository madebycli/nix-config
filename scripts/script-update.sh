#!/usr/bin/env bash
set -Eeuo pipefail

AUTO_YES=0
REPO=""

usage() {
  cat <<'USAGE'
Verwendung:
  script-update                         interaktives Menü
  script-update list
  script-update pull
  script-update replace TOOL DATEI

TOOLS:
  config-sync   -> scripts/config-sync.py
  install       -> scripts/install.sh
  save-config   -> scripts/save-config.sh
  script-update -> scripts/script-update.sh

Beispiele:
  script-update replace config-sync ~/Downloads/config-sync.py
  script-update replace install ~/Downloads/install.sh

'replace' prüft Syntax, zeigt den Diff, sichert nur die alte Skriptdatei und
ersetzt sie erst nach Bestätigung. Commit und Push erfolgen danach manuell mit
config-sync push.
USAGE
}

die() { printf '\nFehler: %s\n' "$*" >&2; exit 1; }
info() { printf '\n==> %s\n' "$*"; }
confirm() {
  (( AUTO_YES == 1 )) && return 0
  printf '\n%s [j/N] ' "$1"
  read -r answer
  case "$answer" in j|J|ja|Ja|JA|y|Y|yes|YES) return 0 ;; *) return 1 ;; esac
}

find_repo() {
  local candidate
  for candidate in \
    "${NIXOS_CONFIG_REPO:-}" \
    "$PWD" \
    "$HOME/$(hostname -s)" \
    "$HOME/nyx" \
    "$HOME/aether"
  do
    [[ -n "$candidate" ]] || continue
    if [[ -d "$candidate/.git" && -f "$candidate/flake.nix" ]]; then
      (cd "$candidate" && pwd)
      return 0
    fi
  done
  return 1
}

tool_path() {
  case "$1" in
    config-sync) printf '%s\n' 'scripts/config-sync.py' ;;
    install) printf '%s\n' 'scripts/install.sh' ;;
    save-config) printf '%s\n' 'scripts/save-config.sh' ;;
    script-update) printf '%s\n' 'scripts/script-update.sh' ;;
    *) return 1 ;;
  esac
}


run_config_sync() {
  if command -v config-sync >/dev/null 2>&1; then
    exec config-sync --repo "$REPO" "$@"
  fi
  exec nix run "$REPO#config-sync" -- --repo "$REPO" "$@"
}

validate_file() {
  local tool="$1" file="$2"
  [[ -f "$file" && ! -L "$file" ]] || die "Nur eine normale Datei ist erlaubt: $file"
  case "$tool" in
    config-sync)
      cache_dir="$(mktemp -d)"
      PYTHONPYCACHEPREFIX="$cache_dir" python3 -m py_compile "$file"
      rm -rf "$cache_dir"
      ;;
    *) bash -n "$file" ;;
  esac
}

replace_tool() {
  local tool="$1" source="$2" relative target timestamp backup
  relative="$(tool_path "$tool")" || die "Unbekanntes Tool: $tool"
  source="$(realpath "$source")"
  target="$REPO/$relative"
  validate_file "$tool" "$source"
  [[ -f "$target" ]] || die "Zieldatei fehlt im Repository: $target"

  if cmp -s "$source" "$target"; then
    printf '\nKeine Änderung: neue und vorhandene Datei sind identisch.\n'
    return 0
  fi

  info "Code-Diff"
  diff -u "$target" "$source" || true
  confirm "Diese neue Datei als '$tool' übernehmen?" || die "Ersetzung abgebrochen."

  timestamp="$(date '+%Y-%m-%d_%H-%M-%S')"
  backup="$HOME/.local/state/nixos-config/script-backups/$timestamp/$relative"
  mkdir -p "$(dirname "$backup")"
  cp -a "$target" "$backup"
  install -m 0755 "$source" "$target"

  info "Ersetzt: $relative"
  printf 'Backup: %s\n' "$backup"
  printf '\nJetzt prüfen und versionieren:\n'
  printf '  config-sync --repo %q status\n' "$REPO"
  printf '  config-sync --repo %q --scope nixos push\n' "$REPO"

  if confirm "Neue Skriptversion jetzt durch NixOS-Build testen?"; then
    profile="$(hostname -s)"
    state_file=""
    while IFS= read -r candidate; do
      if jq -e --arg repository "$REPO" '.repository == $repository' "$candidate" >/dev/null 2>&1; then
        state_file="$candidate"
        break
      fi
    done < <(find "$HOME/.local/state/nixos-config" -name state.json -type f 2>/dev/null || true)
    if [[ -n "$state_file" ]]; then
      state_profile="$(jq -r '.profile // empty' "$state_file")"
      [[ -n "$state_profile" ]] && profile="$state_profile"
    fi
    sudo nixos-rebuild build --flake "$REPO#$profile"
    if confirm "Build erfolgreich. Neue Werkzeuge jetzt aktivieren?"; then
      sudo nixos-rebuild switch --flake "$REPO#$profile"
    fi
  fi
}

while (($#)); do
  case "$1" in
    --repo) shift; (($#)) || die "--repo benötigt einen Pfad."; REPO="$1" ;;
    --yes|-y) AUTO_YES=1 ;;
    --help|-h) usage; exit 0 ;;
    *) break ;;
  esac
  shift
done

if [[ -z "$REPO" ]]; then
  REPO="$(find_repo)" || die "Repository nicht gefunden. --repo angeben."
fi
REPO="$(realpath "$REPO")"

command="${1:-}"
if [[ -z "$command" ]]; then
  printf 'Aktion wählen:\n1) Neue Skriptdatei ersetzen\n2) Skripte aus GitHub aktualisieren\n3) Liste anzeigen\n4) Abbrechen\n> '
  read -r choice
  case "$choice" in
    1)
      printf 'Tool (config-sync/install/save-config/script-update): '
      read -r tool
      printf 'Pfad zur neuen Datei: '
      read -r source
      replace_tool "$tool" "$source"
      ;;
    2) run_config_sync --scope all pull ;;
    3) command="list" ;;
    *) exit 0 ;;
  esac
fi

case "$command" in
  list)
    printf 'config-sync   %s/scripts/config-sync.py\n' "$REPO"
    printf 'install       %s/scripts/install.sh\n' "$REPO"
    printf 'save-config   %s/scripts/save-config.sh\n' "$REPO"
    printf 'script-update %s/scripts/script-update.sh\n' "$REPO"
    ;;
  pull)
    run_config_sync --scope all pull
    ;;
  replace)
    (($# == 3)) || { usage; die "replace benötigt TOOL und DATEI."; }
    replace_tool "$2" "$3"
    ;;
  "") ;;
  *) usage; die "Unbekannter Befehl: $command" ;;
esac
