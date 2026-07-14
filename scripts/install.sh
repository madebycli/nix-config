#!/usr/bin/env bash
set -Eeuo pipefail

readonly REPO_URL="https://github.com/xnixjoyer/nixos-config.git"
readonly REPO_SSH="git@github.com:xnixjoyer/nixos-config.git"
readonly SOURCE_HARDWARE="/etc/nixos/hardware-configuration.nix"
readonly TARGET_USER="xxxxx"
readonly CACHYOS_CACHE_URL="https://attic.xuyh0120.win/lantian"
readonly CACHYOS_CACHE_KEY="lantian:EeAUQ+W+6r7Etwnm