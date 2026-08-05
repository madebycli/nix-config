#!/usr/bin/env bash
set -Eeuo pipefail

case "${1:-}" in
  ""|--help|-h|help) ;;
  *)
    printf 'Error: nix-help does not accept arguments.\n' >&2
    exit 2
    ;;
esac

cat <<'HELP'
NixOS command suite

  config-update              Pull configuration commits, build, and activate

  nix-status                 Show the local system, store, and Git overview
  nix-status --online        Include the GitHub relationship

  nix-updates                Preview all Flake and profile updates
  nix-updates base           Preview Nixpkgs and CachyOS kernel updates
  nix-updates packages       Preview Nixpkgs and profile updates
  nix-updates kernel         Preview only the CachyOS kernel input
  nix-updates desktop        Preview Home Manager, Mango, Noctalia, and Greeter
  nix-updates profiles       Preview only personal Nix profile updates
  nix-updates --full         Build the candidate system and compare packages

  nix-refresh                Update every Flake input and personal profile
  nix-refresh base           Update Nixpkgs, CachyOS kernel, and personal profile
  nix-refresh packages       Update Nixpkgs and personal profile
  nix-refresh kernel         Update only the CachyOS kernel input
  nix-refresh desktop        Update Home Manager, Mango, Noctalia, and Greeter
  nix-refresh profiles       Update only personal Nix profile packages

  nix-generations            List all NixOS system generations
  nix-generations --last 10  List the latest ten generations
  nix-generations --diff A B Compare packages between generations A and B

  nix-clean                  Keep current generation plus five backups
  nix-clean 10               Keep current generation plus ten backups
  nix-clean --dry-run 5      Show generations selected for removal
  nix-clean list             List generations

  nix-optimize               Deduplicate identical Nix Store files
  nix-rollback               Switch to the previous NixOS generation
  nix-help                   Show this overview
HELP
