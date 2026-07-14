#!/usr/bin/env bash
set -Eeuo pipefail

readonly REPO_URL="https://github.com/xnixjoyer/nixos-config.git"
readonly REPO_SSH="git@github.com:xnixjoyer/nixos-config.git"
readonly SOURCE_HARDWARE="/etc/nixos/hardware-configuration.nix"
readonly TARGET_USER="xxxxx"
readonly CACHYOS_CACHE_URL="https://attic.xuyh0120.win/lantian"
readonly CACHYOS_CACHE_KEY="lantian:EeAUQ+W+6r7EtwnmYjeVwx5kOGEBpjlBfPlzGlTNvHc="

HOST=""
MODE="both"
AUTO_YES=0
USE_SSH=0

usage() {
  cat <<'USAGE'
Neuinstallation nach einer normalen NixOS-Grundinstallation:
  nix run github:xnixjoyer/nixos-config#install -- --nyx
  nix run github:xnixjoyer/nixos-config#install -- --aether

Optionen:
  --nyx             Host nyx
  --aether          Host aether
  --mango           nur Mango
  --niri            nur Niri
  --both            Mango und Niri (Standard)
  --ssh              Repository über SSH klonen (SSH-Key