#!/usr/bin/env bash
set -Eeuo pipefail

# First installation (or reinstall) of this configuration on a machine that
# already runs a minimal NixOS. Builds first and switches only after confirmation.

readonly REPO_URL="https://github.com/madebycli/nix-config"
readonly REPO_SSH="git@github.com:madebycli/nix-config.git"
readonly SOURCE_HARDWARE="/etc/nixos/hardware-configuration.nix"

# Ignore all binary caches, including ones configured by the running system.
# CachyOS remains selected; missing store paths are built from source.
readonly -a NIX_BOOTSTRAP_OPTIONS=(
  --option substitute false
  --option substituters ""
  --option connect-timeout 5
  --option fallback true
)

die() { printf 'Error: %s\n' "$*" >&2; exit 1; }
info() { printf '\n==> %s\n' "$*"; }

usage() {
  cat <<'USAGE'
Usage: nix run --refresh github:madebycli/nix-config/BRANCH#install -- --nyx|--aether [options]

  --nyx | --aether   host to install
  --branch NAME      branch to use (default: main)
  --dir PATH         checkout location (default: ~/nix-config)
  --ssh              clone over SSH instead of HTTPS
  --yes              do not ask before activating

Desktop, features and themes are chosen afterwards in hosts/<host>/features.nix
or interactively with `nixctl`.
USAGE
}

HOST="" BRANCH="main" DIR="$HOME/nix-config" USE_SSH=0 ASSUME_YES=0
while (($# > 0)); do
  case "$1" in
    --nyx) HOST=nyx ;;
    --aether) HOST=aether ;;
    --branch) BRANCH="${2:?--branch needs a name}"; shift ;;
    --dir) DIR="${2:?--dir needs a path}"; shift ;;
    --ssh) USE_SSH=1 ;;
    --yes|-y) ASSUME_YES=1 ;;
    -h|--help) usage; exit 0 ;;
    *) usage >&2; die "unknown option: $1" ;;
  esac
  shift
done

[[ -n "$HOST" ]] || { usage >&2; die "choose --nyx or --aether"; }
[[ "$EUID" -ne 0 ]] || die "do not run as root; the script uses sudo where needed"
[[ -e /etc/NIXOS ]] || die "this does not look like an installed NixOS"
[[ -f "$SOURCE_HARDWARE" ]] || die "$SOURCE_HARDWARE is missing"
for command in git nix sudo; do
  command -v "$command" >/dev/null 2>&1 || die "$command is missing"
done

clone_url="$REPO_URL"
((USE_SSH == 1)) && clone_url="$REPO_SSH"

if [[ ! -e "$DIR" ]]; then
  info "Cloning $BRANCH to $DIR"
  git clone --branch "$BRANCH" "$clone_url" "$DIR"
elif [[ ! -d "$DIR/.git" ]]; then
  die "$DIR exists but is not a Git repository"
else
  remote_url="$(git -C "$DIR" remote get-url origin 2>/dev/null || true)"
  [[ "$remote_url" == "$REPO_URL" || "$remote_url" == "$REPO_SSH" || "$remote_url" == "$REPO_URL.git" ]] \
    || die "unexpected Git remote: $remote_url"
  if [[ -z "$(git -C "$DIR" status --porcelain)" ]]; then
    info "Updating existing checkout (fast-forward only)"
    git -C "$DIR" fetch origin "$BRANCH"
    git -C "$DIR" checkout "$BRANCH"
    git -C "$DIR" merge --ff-only "origin/$BRANCH"
  else
    info "Local changes present; leaving the checkout untouched"
    git -C "$DIR" status --short
  fi
fi

[[ -f "$DIR/hosts/$HOST/default.nix" ]] || die "host $HOST is not defined in $DIR"
cd "$DIR"

target="hosts/$HOST/hardware-configuration.nix"
git ls-files --error-unmatch "$target" >/dev/null 2>&1 \
  || die "hardware placeholder is not tracked by Git: $target"
if ! cmp -s "$SOURCE_HARDWARE" "$target"; then
  backup="$HOME/.local/state/nixos-config/install-backups/$(date '+%Y-%m-%d_%H-%M-%S')"
  mkdir -p "$backup"
  cp -a "$target" "$backup/$HOST-hardware-configuration.nix"
  install -m 0644 "$SOURCE_HARDWARE" "$target"
  info "Hardware configuration of this machine written to $target"
fi
# The real hardware file stays on this machine: Nix reads it as a tracked file,
# while commits and pulls leave it alone.
git update-index --skip-worktree "$target"

info "Evaluating $HOST"
nix "${NIX_BOOTSTRAP_OPTIONS[@]}" eval --raw ".#nixosConfigurations.${HOST}.config.networking.hostName" >/dev/null

info "Building $HOST (nothing is activated yet)"
sudo nixos-rebuild build --flake ".#${HOST}" "${NIX_BOOTSTRAP_OPTIONS[@]}"

info "Changes compared to the running system"
nix store diff-closures /run/current-system ./result || true

if ((ASSUME_YES == 0)); then
  read -r -p "Activate this configuration? [y/N] " answer
  [[ "$answer" == [yY]* ]] || { printf '\nNot activated. Build result: %s/result\n' "$DIR"; exit 0; }
fi

info "Activating"
sudo nixos-rebuild switch --flake ".#${HOST}" "${NIX_BOOTSTRAP_OPTIONS[@]}"

sudo install -d -m 0755 /var/lib/nixos-config
sudo touch /var/lib/nixos-config/fstrim-pending

if command -v dots >/dev/null 2>&1; then
  info "Linking synchronised app configuration"
  dots link || true
  printf 'Existing local app folders can be moved into the repository with: dots adopt\n'
fi

printf '\nDone.\nHost: %s\nRepository: %s (%s)\n' "$HOST" "$DIR" "$BRANCH"
printf 'Next: nixctl (features), nx check (updates), sudo plmf theme list (boot splash), dots on (config sync).\n'
