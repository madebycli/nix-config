# nixctl - switch features of this machine on and off.
#
# Edits hosts/<host>/features.nix in the repository and, after a preview of
# what changes, rebuilds the system. Nothing is activated before you confirm.

readonly CONF="${NIXCTL_CONF:-/etc/nixctl.conf}"
REPO="" HOST=""
# shellcheck disable=SC1090
. "$CONF"
[[ -n "$REPO" && -n "$HOST" ]] || { echo "nixctl: bad $CONF" >&2; exit 1; }
readonly FILE="$REPO/hosts/$HOST/features.nix"
[[ -f "$FILE" ]] || { echo "nixctl: $FILE not found" >&2; exit 1; }

die() { echo "nixctl: $*" >&2; exit 1; }

feature_re='^[[:space:]]*(#[[:space:]]*)?my\.features\.([A-Za-z0-9_-]+)\.enable[[:space:]]*=[[:space:]]*(true|false);'

list_features() {
  # prints: name<TAB>on|off
  sed -nE "s/$feature_re.*/\2\t\3/p" "$FILE" |
    sed -E 's/\ttrue$/\ton/; s/\tfalse$/\toff/'
}

set_feature() {
  local name="$1" value="$2"
  [[ "$name" =~ ^[A-Za-z0-9_-]+$ ]] || die "invalid feature name"
  grep -qE "^[[:space:]]*my\.features\.$name\.enable[[:space:]]*=" "$FILE" ||
    die "unknown feature '$name' (see: nixctl list)"
  sed -i -E "s/^([[:space:]]*my\.features\.$name\.enable[[:space:]]*=[[:space:]]*)(true|false);/\1$value;/" "$FILE"
}

cmd_list() {
  list_features | while IFS=$'\t' read -r name state; do
    printf '%-12s %s\n' "$name" "$state"
  done
  echo
  grep -E '^[[:space:]]*my\.(kernel|desktop\.)' "$FILE" | sed -E 's/^[[:space:]]*/  /'
}

cmd_apply() {
  local action="${1:-switch}"
  case "$action" in switch | boot | test | build) ;; *) die "apply: switch|boot|test|build" ;; esac
  echo "nixctl: building $HOST ..."
  local out
  out="$(mktemp -d)"
  nixos-rebuild build --flake "$REPO#$HOST" --out-link "$out/result"
  echo
  echo "nixctl: changes compared to the running system:"
  nix store diff-closures /run/current-system "$out/result" || true
  [[ "$action" == build ]] && { echo "nixctl: built only ($out/result)"; return 0; }
  echo
  if gum confirm "Activate ($action)?"; then
    sudo nixos-rebuild "$action" --flake "$REPO#$HOST"
  else
    echo "nixctl: not activated. features.nix keeps your edits (git diff shows them)."
  fi
}

cmd_interactive() {
  local rows selected chosen name
  local names=()
  rows="$(list_features)"
  [[ -n "$rows" ]] || die "no features found in $FILE"
  mapfile -t names < <(cut -f1 <<<"$rows")
  selected="$(awk -F'\t' '$2=="on"{print $1}' <<<"$rows" | paste -sd, -)"
  echo "Space toggles, Enter confirms."
  chosen="$(gum choose --no-limit --selected="$selected" --header "Features on $HOST" "${names[@]}")" || exit 0
  for name in "${names[@]}"; do
    if grep -qx "$name" <<<"$chosen"; then set_feature "$name" true; else set_feature "$name" false; fi
  done
  git -C "$REPO" --no-pager diff --stat -- "$FILE" || true
  if gum confirm "Rebuild now?"; then cmd_apply switch; fi
}

cmd_desktop() {
  local session shell list
  local comps=()
  mapfile -t comps < <(gum choose --no-limit --header "Compositors" mango niri hyprland) || exit 0
  [[ ${#comps[@]} -gt 0 ]] || die "choose at least one compositor"
  session="$(gum choose --header "Default session" "${comps[@]}")" || exit 0
  shell=noctalia
  if [[ ${#comps[@]} -eq 1 && "${comps[0]}" == hyprland ]]; then
    shell="$(gum choose --header "Shell" noctalia caelestia)" || exit 0
  fi
  list=""
  for c in "${comps[@]}"; do list+="\"$c\" "; done
  sed -i -E "s/^([[:space:]]*my\.desktop\.compositors[[:space:]]*=).*/\1 [ $list];/; s/^([[:space:]]*my\.desktop\.defaultSession[[:space:]]*=).*/\1 \"$session\";/; s/^([[:space:]]*my\.desktop\.shell[[:space:]]*=).*/\1 \"$shell\";/" "$FILE"
  cmd_list
  if gum confirm "Rebuild now?"; then cmd_apply switch; fi
}

cmd_kernel() {
  local kernel="${1:-}" current
  current="$(sed -nE 's/^[[:space:]]*my\.kernel[[:space:]]*=[[:space:]]*"([^"]+)";.*/\1/p' "$FILE")"
  [[ "$current" == latest || "$current" == cachyos ]] || die "missing or ambiguous my.kernel in $FILE"
  if [[ -z "$kernel" ]]; then
    kernel="$(gum choose --selected="$current" --header "Kernel on $HOST" latest cachyos)" || return 0
  fi
  case "$kernel" in latest | cachyos) ;; *) die "kernel: latest|cachyos" ;; esac
  sed -i -E "s/^([[:space:]]*my\.kernel[[:space:]]*=[[:space:]]*)\"[^\"]+\";/\1\"$kernel\";/" "$FILE"
  cmd_list
  if gum confirm "Rebuild now?"; then cmd_apply switch; fi
}

usage() {
  cat <<'EOF2'
nixctl                 interactive feature list (space toggles)
nixctl list            show feature switches of this host
nixctl on  FEATURE     switch a feature on  (edits features.nix)
nixctl off FEATURE     switch a feature off
nixctl desktop         choose compositors and shell interactively
nixctl kernel [NAME]   choose latest|cachyos (default: interactive)
nixctl apply [MODE]    build, show the diff, then switch|boot|test (default: switch)
EOF2
}

cmd="${1:-interactive}"
[[ $# -gt 0 ]] && shift
case "$cmd" in
  interactive) cmd_interactive ;;
  list) cmd_list ;;
  on) set_feature "${1:?feature name}" true; cmd_list ;;
  off) set_feature "${1:?feature name}" false; cmd_list ;;
  desktop) cmd_desktop ;;
  kernel) cmd_kernel "$@" ;;
  apply) cmd_apply "$@" ;;
  help | -h | --help) usage ;;
  *) usage; exit 2 ;;
esac
