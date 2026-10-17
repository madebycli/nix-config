#!/usr/bin/env bash
# Simulates two machines syncing app config through a bare Git remote.
# Usage: DOTS=/path/to/bin/dots tests/dots-test.sh
set -Eeuo pipefail

DOTS="${DOTS:?set DOTS to the dots binary}"
T="$(mktemp -d)"
trap 'rm -rf "$T"' EXIT
cd "$T"
export DBUS_SESSION_BUS_ADDRESS=disabled:
export GIT_CONFIG_GLOBAL="$T/gitconfig"
git config --global user.name test
git config --global user.email test@example.invalid

fail() { echo "FAIL: $*" >&2; exit 1; }
run() { local pc=$1; shift; HOME="$T/home$pc" DOTS_CONF="$T/conf$pc" "$DOTS" "$@" 2>&1; }

git init -q --bare -b main remote.git
git init -q -b main seed
(
  cd seed
  git commit -q --allow-empty -m init
  mkdir -p config/mango
  echo "bind=A" >config/mango/config.conf
  git add -A
  git commit -qm seed
  git remote add origin "$T/remote.git"
  git push -q origin main
)
for pc in a b; do
  git clone -q remote.git "pc$pc"
  mkdir -p "home$pc/.config"
  printf 'REPO=%s\nAPPS="mango niri"\n' "$T/pc$pc" >"conf$pc"
done

# Existing local folder is not silently merged with repository content.
mkdir -p homea/.config/mango
echo local >homea/.config/mango/x
run a link >/dev/null
output=$(run a adopt mango) || fail "dots adopt failed: $output"
grep -q "refusing to merge" <<<"$output" || fail "adopt must refuse when the repo already has the app: $output"

# Auto-sync does nothing while switched off.
run b link >/dev/null
echo "bind=B" >homeb/.config/mango/config.conf
before="$(git -C pcb rev-list --count HEAD)"
run b auto >/dev/null
[[ "$(git -C pcb rev-list --count HEAD)" == "$before" ]] || fail "auto committed while switched off"

# Switched on: change is committed and pushed, the other machine receives it.
run b on >/dev/null
run b auto >/dev/null
git -C remote.git log --format=%s main | grep -q '^dots:' || fail "change was not pushed"
rm -rf homea/.config/mango
run a link >/dev/null
run a sync >/dev/null
grep -qx "bind=B" homea/.config/mango/config.conf || fail "machine A did not receive the change"

# Conflicting edits: rebase is aborted, auto-sync switches itself off.
echo "bind=A2" >homea/.config/mango/config.conf
echo "bind=B2" >homeb/.config/mango/config.conf
run b on >/dev/null
run b auto >/dev/null
run a on >/dev/null
run a auto >/dev/null || true
[[ ! -e homea/.local/state/dots/auto-sync ]] || fail "auto-sync stayed on after a conflict"
[[ -z "$(git -C pca status --porcelain --untracked-files=no | grep -v '^$' || true)" ]] || fail "conflict left the work tree dirty"

# Oversized files are never committed.
head -c 6000000 /dev/zero >homeb/.config/niri/big.bin
run b on >/dev/null
output=$(run b auto) || fail "dots auto failed: $output"
grep -q "skipped" <<<"$output" || fail "big file was not skipped: $output"
git -C pcb ls-files | grep -q big.bin && fail "big file was committed"

echo "dots tests passed"
