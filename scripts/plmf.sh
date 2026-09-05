#!/usr/bin/env bash
set -euo pipefail

allowed_file=${PLMF_ALLOWED_FILE:-/etc/plmf/allowed-themes}
default_file=${PLMF_DEFAULT_FILE:-/etc/plmf/default-theme}
metadata_file=${PLMF_METADATA_FILE:-/etc/plmf/theme-metadata}
efi_mount_file=${PLMF_EFI_MOUNT_FILE:-/etc/plmf/efi-mount-point}
selector_relative_file=${PLMF_SELECTOR_RELATIVE_FILE:-/etc/plmf/selector-relative-path}
theme_root=${PLMF_THEME_ROOT:-/etc/plymouth/themes}
plugin_root=${PLMF_PLUGIN_ROOT:-/etc/plymouth/plugins}

fail() {
  printf 'plmf: %s\n' "$*" >&2
  exit 1
}

require_file() {
  [[ -r "$1" ]] || fail "required file is not readable: $1"
}

read_single_line() {
  local file=$1
  local value

  require_file "$file"
  IFS= read -r value < "$file" || true
  [[ -n "$value" ]] || fail "required value is empty: $file"
  printf '%s\n' "$value"
}

is_allowed() {
  local name=$1
  require_file "$allowed_file"
  grep -Fxq -- "$name" "$allowed_file"
}

selector_path() {
  local efi_mount
  local relative

  efi_mount=$(read_single_line "$efi_mount_file")
  relative=$(read_single_line "$selector_relative_file")
  printf '%s/%s\n' "${efi_mount%/}" "${relative#/}"
}

valid_override() {
  local selector=$1
  local candidate
  local size

  [[ -f "$selector" ]] || return 1
  size=$(stat -c '%s' -- "$selector" 2>/dev/null || printf '999999')
  [[ "$size" =~ ^[0-9]+$ ]] || return 1
  (( size <= 128 )) || return 1

  while IFS= read -r candidate; do
    [[ -n "$candidate" ]] || continue
    if printf '%s\n' "$candidate" | cmp -s - "$selector"; then
      printf '%s\n' "$candidate"
      return 0
    fi
  done < "$allowed_file"

  return 1
}

require_root() {
  (( EUID == 0 )) || fail "this command must be run as root"
}

require_efi_mount() {
  local efi_mount=$1
  findmnt -rn --mountpoint "$efi_mount" >/dev/null 2>&1 || \
    fail "EFI system partition is not mounted at $efi_mount"
}

show_current() {
  local declared_default
  local selector
  local override=''
  local effective

  declared_default=$(read_single_line "$default_file")
  is_allowed "$declared_default" || fail "declarative default is not in the bundled allowlist"
  selector=$(selector_path)

  if override=$(valid_override "$selector"); then
    effective=$override
  else
    effective=$declared_default
  fi

  printf 'Declarative default: %s\n' "$declared_default"
  if [[ -n "$override" ]]; then
    printf 'Runtime override:   %s\n' "$override"
  elif [[ -e "$selector" ]]; then
    printf 'Runtime override:   invalid, ignored\n'
  else
    printf 'Runtime override:   none\n'
  fi
  printf 'Next boot theme:    %s\n' "$effective"
}

list_themes() {
  local name
  local description

  require_file "$allowed_file"
  require_file "$metadata_file"

  while IFS= read -r name; do
    [[ -n "$name" ]] || continue
    description=$(awk -F '\t' -v wanted="$name" '$1 == wanted { sub(/^[^\t]*\t/, ""); print; exit }' "$metadata_file")
    if [[ -n "$description" ]]; then
      printf '%-16s %s\n' "$name" "$description"
    else
      printf '%s\n' "$name"
    fi
  done < "$allowed_file"
}

search_themes() {
  local needle=$1
  local name
  local description
  local haystack
  local matched=0

  [[ -n "$needle" ]] || fail "search text must not be empty"
  require_file "$allowed_file"
  require_file "$metadata_file"

  shopt -s nocasematch
  while IFS= read -r name; do
    [[ -n "$name" ]] || continue
    description=$(awk -F '\t' -v wanted="$name" '$1 == wanted { sub(/^[^\t]*\t/, ""); print; exit }' "$metadata_file")
    haystack="$name $description"
    if [[ "$haystack" == *"$needle"* ]]; then
      printf '%-16s %s\n' "$name" "$description"
      matched=1
    fi
  done < "$allowed_file"
  shopt -u nocasematch

  (( matched == 1 )) || return 1
}

set_theme() {
  local name=$1
  local efi_mount
  local selector
  local selector_dir
  local tmp=''

  require_root
  is_allowed "$name" || fail "theme is not bundled: $name"

  efi_mount=$(read_single_line "$efi_mount_file")
  require_efi_mount "$efi_mount"
  selector=$(selector_path)
  selector_dir=$(dirname -- "$selector")
  install -d -m 0755 -- "$selector_dir"

  tmp=$(mktemp "$selector_dir/.theme.tmp.XXXXXX")
  trap '[[ -z "${tmp:-}" ]] || rm -f -- "$tmp"' EXIT

  printf '%s\n' "$name" > "$tmp"
  chmod 0644 "$tmp"
  sync "$tmp"
  mv -f -- "$tmp" "$selector"
  tmp=''
  sync -f "$selector_dir" 2>/dev/null || sync
  trap - EXIT

  printf 'Runtime theme set to %s for the next boot.\n' "$name"
}

reset_theme() {
  local efi_mount
  local selector
  local selector_dir

  require_root
  efi_mount=$(read_single_line "$efi_mount_file")
  require_efi_mount "$efi_mount"
  selector=$(selector_path)
  selector_dir=$(dirname -- "$selector")

  if [[ -e "$selector" ]]; then
    rm -f -- "$selector"
    sync -f "$selector_dir" 2>/dev/null || sync
  fi

  printf 'Runtime theme override removed.\n'
}

test_theme() {
  local name=$1
  local theme_dir
  local descriptor
  local module_name
  local script_file
  local script_name

  is_allowed "$name" || fail "theme is not bundled: $name"

  theme_dir="$theme_root/$name"
  descriptor="$theme_dir/$name.plymouth"
  require_file "$descriptor"

  module_name=$(awk -F '=' '/^[[:space:]]*ModuleName[[:space:]]*=/ { sub(/^[^=]*=/, ""); gsub(/^[[:space:]]+|[[:space:]]+$/, ""); print; exit }' "$descriptor")
  [[ -n "$module_name" ]] || fail "theme descriptor has no ModuleName: $descriptor"
  [[ "$module_name" =~ ^[A-Za-z0-9._-]+$ ]] || fail "theme descriptor has an unsafe ModuleName"
  [[ -r "$plugin_root/$module_name.so" ]] || fail "Plymouth plugin is missing: $plugin_root/$module_name.so"

  if [[ "$module_name" == 'script' ]]; then
    script_file=$(awk -F '=' '/^[[:space:]]*ScriptFile[[:space:]]*=/ { sub(/^[^=]*=/, ""); gsub(/^[[:space:]]+|[[:space:]]+$/, ""); print; exit }' "$descriptor")
    [[ -n "$script_file" ]] || fail "script theme has no ScriptFile: $descriptor"
    script_name=${script_file##*/}
    [[ "$script_name" =~ ^[A-Za-z0-9._-]+$ ]] || fail "theme descriptor has an unsafe ScriptFile"
    require_file "$theme_dir/$script_name"
  fi

  printf 'Theme %s passed local static validation.\n' "$name"
  printf 'No VM was started. Full UEFI boot validation runs in the beta branch CI.\n'
}

usage() {
  cat <<'EOF'
Usage:
  plmf theme current
  plmf theme list
  plmf theme search <text>
  sudo plmf theme set <name>
  sudo plmf theme reset
  plmf theme test <name>

Notes:
  theme test only performs safe local static validation. It never launches QEMU.
EOF
}

[[ ${1:-} == 'theme' ]] || {
  usage >&2
  exit 2
}

case ${2:-} in
  current)
    [[ $# -eq 2 ]] || fail "theme current takes no arguments"
    show_current
    ;;
  list)
    [[ $# -eq 2 ]] || fail "theme list takes no arguments"
    list_themes
    ;;
  search)
    [[ $# -eq 3 ]] || fail "usage: plmf theme search <text>"
    search_themes "$3"
    ;;
  set)
    [[ $# -eq 3 ]] || fail "usage: sudo plmf theme set <name>"
    set_theme "$3"
    ;;
  reset)
    [[ $# -eq 2 ]] || fail "theme reset takes no arguments"
    reset_theme
    ;;
  test)
    [[ $# -eq 3 ]] || fail "usage: plmf theme test <name>"
    test_theme "$3"
    ;;
  *)
    usage >&2
    exit 2
    ;;
esac
