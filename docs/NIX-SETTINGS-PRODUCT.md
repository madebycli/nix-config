# Nix Settings product architecture

This branch replaces the user-facing collection of maintenance/profile commands
with a product layer named **Nix Settings**.

## TUI provenance

The terminal UI deliberately uses Linutil as its implementation base. An exact
snapshot of Linutil's TUI from `0b0f7449e79275a7ad5cd1c0dee48c6d71f1f7f1` is kept under
`nix-settings/vendor/linutil-tui`. Selected upstream modules are compiled
directly by Nix Settings. Adapted files are kept separate so upstream copyright
and modifications remain clear. See `THIRD_PARTY_NOTICES.md`.

## Layout

The TUI keeps Linutil's core interaction model: left navigation/system panel,
right search + item list, context shortcuts along the bottom, modal confirmation,
and a real PTY for command output.

Nix Settings pages are product-specific:

- Overview
- Configure
- Updates
- Packages
- Config Sync
- Integrations
- Generations
- Maintenance
- Diagnostics

## Desired state

There is one NixOS configuration per host (`nyx`, `aether`). User choices live
in `state/<host>.json`; the combinatorial desktop profile matrix is not part of
the managed interface anymore. The TUI edits this state and `Save & Apply`
runs a normal `nixos-rebuild switch --flake .#<host>`.

## Integrations

`modules/nixos/product-features.nix` maps desired-state features to NixOS:
software bundles, browser selection, and Filen. Filen Desktop can be installed
and started automatically as a user service; Filen CLI can be installed but is
not blindly autostarted because continuous CLI sync needs explicit sync pairs.

## Migration

The old maintenance/sync executables remain in the branch as compatibility
backends while functionality is moved into the Rust core. The TUI is the normal
interface and does not require users to remember `--scope` or profile names.
