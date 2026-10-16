#!/usr/bin/env bash
set -Eeuo pipefail

# config-update: bring in newer configuration commits (fast-forward only),
# build, show what changes and switch after confirmation.

usage() {
  cat <<'USAGE'
Usage: config-update [--yes] [--boot|--test]

Pulls the tracked branch of your configuration repository without merge
commits, builds the system, shows the closure diff and activates it.

  --yes    do not ask before activating
  --boot   activate on next boot only
  --test   activate without adding a boot entry
USAGE
}

ACTION=switch
ASSUME_YES=0
for arg in "$@"; do
  case "$arg" in
    --yes|-y) ASSUME_YES=1 ;;
    --boot) ACTION=boot ;;
    --test) ACTION=test ;;
    -h|--help) usage; exit 0 ;;
    *) printf 'Error: unknown option %s\n' "$arg" >&2; usage >&2; exit 2 ;;
  esac
done

HOST="$(hostname -s)"
REPO="$(sed -n "s/^REPO=//p" /etc/nixctl.conf 2>/dev/null | tr -d "'\"")"
REPO="${REPO:-$HOME/nix-config}"
[[ -d "$REPO/.git" ]] || { printf 'Error: %s is not a Git checkout.\n' "$REPO" >&2; exit 1; }

BRANCH="$(git -C "$REPO" branch --show-current)"
[[ -n "$BRANCH" ]] || { printf 'Error: no branch is checked out in %s.\n' "$REPO" >&2; exit 1; }

printf '==> Fetching %s\n' "$BRANCH"
git -C "$REPO" fetch --prune origin "$BRANCH"
AHEAD="$(git -C "$REPO" rev-list --count "origin/$BRANCH..HEAD")"
BEHIND="$(git -C "$REPO" rev-list --count "HEAD..origin/$BRANCH")"

if ((AHEAD > 0 && BEHIND > 0)); then
  printf 'Error: local and remote history diverged (%s ahead, %s behind). Resolve in %s.\n' "$AHEAD" "$BEHIND" "$REPO" >&2
  exit 1
fi
if ((BEHIND > 0)); then
  # Autostash keeps uncommitted work (e.g. synchronised dotfiles) intact.
  git -C "$REPO" pull --ff-only --autostash origin "$BRANCH"
else
  printf 'Already up to date with origin/%s.\n' "$BRANCH"
fi

OUT="$(mktemp -d)"
trap 'rm -rf "$OUT"' EXIT

printf '\n==> Building %s\n' "$HOST"
nixos-rebuild build --flake "$REPO#$HOST" --out-link "$OUT/result"

printf '\n==> Changes compared to the running system\n'
nix store diff-closures /run/current-system "$OUT/result" || true

if ((ASSUME_YES == 0)); then
  read -r -p "Activate ($ACTION)? [y/N] " answer
  [[ "$answer" == [yY]* ]] || { printf 'Not activated.\n'; exit 0; }
fi

sudo nixos-rebuild "$ACTION" --flake "$REPO#$HOST"
sudo install -d -m 0755 /var/lib/nixos-config
sudo touch /var/lib/nixos-config/fstrim-pending
printf '\nActive: %s#%s\n' "$REPO" "$HOST"
