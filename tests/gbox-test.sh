#!/usr/bin/env bash
# Checks the isolation guarantees of gbox that need no display, GPU or network.
# Needs unprivileged user namespaces. Usage: GBOX=/path/to/bin/gbox tests/gbox-test.sh
set -Eeuo pipefail

GBOX="${GBOX:?set GBOX to the gbox binary}"
T="$(mktemp -d)"
trap 'rm -rf "$T"' EXIT
export HOME="$T/home" XDG_RUNTIME_DIR="$T/run"
mkdir -p "$HOME" "$XDG_RUNTIME_DIR"
chmod 700 "$XDG_RUNTIME_DIR"

fail() { echo "FAIL: $*" >&2; exit 1; }

echo "secret" >"$HOME/secret.txt"
mkdir -p "$HOME/.ssh"
echo "key" >"$HOME/.ssh/id_test"

X="$(mktemp -d)"
trap 'rm -rf "$T" "$X"' EXIT
cat >"$X/check.sh" <<'CHECK'
test ! -e "$HOME/secret.txt" || exit 11
test ! -e "$HOME/.ssh" || exit 12
# Only the loopback interface may exist (no host network namespace).
others="$(tail -n +3 /proc/net/dev | cut -d: -f1 | tr -d ' ' | grep -vx lo || true)"
test -z "$others" || exit 13
test -z "${WAYLAND_DISPLAY:-}" || exit 14
test -z "${DISPLAY:-}" || exit 15
echo ok-isolated
CHECK

"$GBOX" new t --net none --display none --no-gpu --no-audio --ro "$X" -- bash "$X/check.sh" >/dev/null

out="$("$GBOX" run t)" || fail "isolation check exited with $?"
[[ "$out" == *ok-isolated* ]] || fail "sandbox command did not run: $out"

# Dangerous shares are refused.
"$GBOX" new bad --display none --no-gpu --no-audio --share "$HOME" -- true >/dev/null
if "$GBOX" run bad >/dev/null 2>&1; then fail "sharing \$HOME must be refused"; fi
"$GBOX" new bad2 --display none --no-gpu --no-audio --share "$HOME/.ssh" -- true >/dev/null
if "$GBOX" run bad2 >/dev/null 2>&1; then fail "sharing ~/.ssh must be refused"; fi

# Newlines would corrupt the profile format.
if "$GBOX" new nl --display none -- bash -c $'echo a\necho b' >/dev/null 2>&1; then
  fail "newline in a command must be rejected"
fi

echo "gbox tests passed"
