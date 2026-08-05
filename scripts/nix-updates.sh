#!/usr/bin/env bash
set -Eeuo pipefail

readonly TARGET_USER="xxxxx"
readonly REPO_HTTPS="https://github.com/madebycli/nix-config.git"
readonly REPO_SSH="git@github.com:madebycli/nix-config.git"

usage() {
  cat <<'USAGE'
Verwendung:
  nix-updates [all|base|packages|kernel|desktop|profiles] [--full]

Prüft Updates ohne die echte flake.lock oder das laufende System zu verändern.
--full baut zusätzlich die mögliche neue System-Closure und vergleicht Pakete.
USAGE
}

MODE=all
FULL=0
mode_seen=0
for argument in "$@"; do
  case "$argument" in
    --full) FULL=1 ;;
    --help|-h|help) usage; exit 0 ;;
    all|base|packages|kernel|desktop|profiles)
      ((mode_seen == 0)) || { printf 'Fehler: nur ein Modus ist erlaubt.\n' >&2; exit 2; }
      MODE="$argument"
      mode_seen=1
      ;;
    *) usage; printf '\nFehler: unbekanntes Argument: %s\n' "$argument" >&2; exit 2 ;;
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

[[ "$(id -un)" == "$TARGET_USER" ]] || { printf 'Fehler: als Benutzer %s starten.\n' "$TARGET_USER" >&2; exit 1; }

host="$(hostname -s)"
case "$host" in nyx|aether) ;; *) printf 'Fehler: Hostname muss nyx oder aether sein.\n' >&2; exit 1 ;; esac
repo="$HOME/$host"
profile="$host"
while IFS= read -r state_file; do
  [[ -f "$state_file" ]] || continue
  state_repo="$(jq -r '.repository // empty' "$state_file" 2>/dev/null || true)"
  [[ "$state_repo" == "$repo" ]] || continue
  candidate="$(jq -r '.profile // empty' "$state_file" 2>/dev/null || true)"
  case "$candidate" in "$host"|"$host-mango"|"$host-niri") profile="$candidate" ;; esac
  break
done < <(find "$HOME/.local/state/nixos-config" -name state.json -type f 2>/dev/null || true)

if [[ "$MODE" != profiles ]]; then
  [[ -d "$repo/.git" && -f "$repo/flake.nix" && -f "$repo/flake.lock" ]] || { printf 'Fehler: vollständiges Repository fehlt: %s\n' "$repo" >&2; exit 1; }
  remote="$(git -C "$repo" remote get-url origin)"
  [[ "$remote" == "$REPO_HTTPS" || "$remote" == "$REPO_SSH" ]] || { printf 'Fehler: unerwartetes Git-Remote: %s\n' "$remote" >&2; exit 1; }

  printf '\n==> Repository-Stand\n'
  git -C "$repo" fetch --prune origin
  branch="$(git -C "$repo" branch --show-current)"
  read -r ahead behind < <(git -C "$repo" rev-list --left-right --count "HEAD...origin/$branch")
  printf 'GitHub: lokal voraus %s · lokal zurück %s\n' "$ahead" "$behind"

  temp_root="$(mktemp -d -t nix-updates.XXXXXXXX)"
  trap 'rm -rf "$temp_root"' EXIT INT TERM
  temp_repo="$temp_root/repo"
  cp -a "$repo" "$temp_repo"

  printf '\n==> Flake-Inputs werden in einer temporären Kopie geprüft\n'
  nix flake update "${INPUTS[@]}" --flake "$temp_repo" --refresh

  node_for_input() {
    local lock="$1" input="$2"
    jq -r --arg input "$input" '.nodes.root.inputs[$input] | if type == "string" then . elif type == "array" then .[-1] else empty end' "$lock"
  }

  describe_input() {
    local lock="$1" input="$2" node rev stamp date_value
    node="$(node_for_input "$lock" "$input")"
    [[ -n "$node" ]] || { printf 'unbekannt'; return; }
    rev="$(jq -r --arg node "$node" '.nodes[$node].locked.rev // .nodes[$node].locked.narHash // "unbekannt"' "$lock")"
    stamp="$(jq -r --arg node "$node" '.nodes[$node].locked.lastModified // 0' "$lock")"
    if [[ "$stamp" =~ ^[1-9][0-9]*$ ]]; then
      date_value="$(date -d "@$stamp" +%Y-%m-%d 2>/dev/null || true)"
    else
      date_value=""
    fi
    [[ ${#rev} -le 12 ]] || rev="${rev:0:12}"
    if [[ -n "$date_value" ]]; then printf '%s · %s' "$date_value" "$rev"; else printf '%s' "$rev"; fi
  }

  printf '\nFlake-Inputs:\n'
  for input in "${INPUTS[@]}"; do
    old="$(describe_input "$repo/flake.lock" "$input")"
    new="$(describe_input "$temp_repo/flake.lock" "$input")"
    if [[ "$old" == "$new" ]]; then
      printf '  %-22s %s  (aktuell)\n' "$input" "$old"
    else
      printf '  %-22s %s  ->  %s\n' "$input" "$old" "$new"
    fi
  done

  if ((FULL == 1)); then
    printf '\n==> Mögliche neue System-Closure wird gebaut: %s\n' "$profile"
    new_system="$(nix build "$temp_repo#nixosConfigurations.${profile}.config.system.build.toplevel" --no-link --print-out-paths)"
    printf '\nPaket- und Größenänderungen:\n'
    nix store diff-closures /run/current-system "$new_system"
  fi
fi

if ((CHECK_PROFILE == 1)); then
  printf '\n==> Persönliche Nix-Profilpakete\n'
  if ! nix profile upgrade --all --refresh --dry-run; then
    printf 'Hinweis: Profilvorschau konnte nicht vollständig ausgeführt werden.\n' >&2
  fi
fi

printf '\nEs wurde weder geswitcht noch die echte flake.lock verändert.\n'
