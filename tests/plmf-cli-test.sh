#!/usr/bin/env bash
set -euo pipefail

repo_root=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
tmp=$(mktemp -d)
esp="$tmp/esp"
config_dir="$tmp/config"
theme_root="$tmp/themes"
plugin_root="$tmp/plugins"
selector_rel='EFI/PLMF/theme'
selector="$esp/$selector_rel"

cleanup() {
  sudo umount "$esp" >/dev/null 2>&1 || true
  rm -rf "$tmp"
}
trap cleanup EXIT

mkdir -p "$esp" "$config_dir" "$theme_root/minimal" "$theme_root/zoot" "$plugin_root"
sudo mount -t tmpfs -o nosuid,nodev,noexec tmpfs "$esp"
sudo chown "$(id -u):$(id -g)" "$esp"

printf 'minimal\nzoot\n' > "$config_dir/allowed-themes"
printf 'minimal\n' > "$config_dir/default-theme"
printf 'minimal\tMinimal PLMF boot splash\nzoot\tZOOT terminal boot sequence\n' > "$config_dir/theme-metadata"
printf '%s\n' "$esp" > "$config_dir/efi-mount-point"
printf '%s\n' "$selector_rel" > "$config_dir/selector-relative-path"

for theme in minimal zoot; do
  cat > "$theme_root/$theme/$theme.plymouth" <<EOF
[Plymouth Theme]
Name=$theme
ModuleName=script

[script]
ScriptFile=/etc/plymouth/themes/$theme/$theme.script
EOF
  printf '# static test fixture\n' > "$theme_root/$theme/$theme.script"
done
printf 'fixture\n' > "$plugin_root/script.so"

env_args=(
  "PLMF_ALLOWED_FILE=$config_dir/allowed-themes"
  "PLMF_DEFAULT_FILE=$config_dir/default-theme"
  "PLMF_METADATA_FILE=$config_dir/theme-metadata"
  "PLMF_EFI_MOUNT_FILE=$config_dir/efi-mount-point"
  "PLMF_SELECTOR_RELATIVE_FILE=$config_dir/selector-relative-path"
  "PLMF_THEME_ROOT=$theme_root"
  "PLMF_PLUGIN_ROOT=$plugin_root"
)

run_plmf() {
  env "${env_args[@]}" bash "$repo_root/scripts/plmf.sh" "$@"
}

run_plmf_root() {
  sudo env "${env_args[@]}" bash "$repo_root/scripts/plmf.sh" "$@"
}

write_selector() {
  printf '%s\n' "$1" | sudo tee "$selector" >/dev/null
}

assert_contains() {
  local haystack=$1
  local needle=$2
  [[ "$haystack" == *"$needle"* ]] || {
    printf 'expected output to contain: %s\noutput:\n%s\n' "$needle" "$haystack" >&2
    exit 1
  }
}

output=$(run_plmf theme current)
assert_contains "$output" 'Declarative default: minimal'
assert_contains "$output" 'Runtime override:   none'
assert_contains "$output" 'Next boot theme:    minimal'

output=$(run_plmf theme list)
assert_contains "$output" 'minimal'
assert_contains "$output" 'zoot'

output=$(run_plmf theme search zOoT)
assert_contains "$output" 'zoot'

output=$(run_plmf theme test zoot)
assert_contains "$output" 'Theme zoot passed local static validation.'
assert_contains "$output" 'No VM was started.'

rm -f "$plugin_root/script.so"
if run_plmf theme test minimal; then
  printf 'static test accepted a missing Plymouth plugin\n' >&2
  exit 1
fi
printf 'fixture\n' > "$plugin_root/script.so"

run_plmf_root theme set zoot
[[ $(cat "$selector") == 'zoot' ]]
output=$(run_plmf theme current)
assert_contains "$output" 'Runtime override:   zoot'
assert_contains "$output" 'Next boot theme:    zoot'

# Simulate a rebuild regenerating declarative metadata while leaving the ESP selector untouched.
printf 'minimal\n' > "$config_dir/default-theme"
output=$(run_plmf theme current)
assert_contains "$output" 'Next boot theme:    zoot'

if run_plmf_root theme set '../foo'; then
  printf 'unsafe path-like theme name was accepted\n' >&2
  exit 1
fi

if run_plmf_root theme set 'x;reboot'; then
  printf 'shell-metacharacter theme name was accepted\n' >&2
  exit 1
fi

write_selector '../foo'
output=$(run_plmf theme current)
assert_contains "$output" 'Runtime override:   invalid, ignored'
assert_contains "$output" 'Next boot theme:    minimal'

sudo truncate -s 0 "$selector"
output=$(run_plmf theme current)
assert_contains "$output" 'Runtime override:   invalid, ignored'

write_selector 'removed-theme'
output=$(run_plmf theme current)
assert_contains "$output" 'Runtime override:   invalid, ignored'

write_selector 'x;reboot'
output=$(run_plmf theme current)
assert_contains "$output" 'Runtime override:   invalid, ignored'

sudo rm -f "$selector"
output=$(run_plmf theme current)
assert_contains "$output" 'Runtime override:   none'
assert_contains "$output" 'Next boot theme:    minimal'

run_plmf_root theme set minimal
run_plmf_root theme reset
[[ ! -e "$selector" ]]

printf 'PLMF CLI selector tests passed.\n'
