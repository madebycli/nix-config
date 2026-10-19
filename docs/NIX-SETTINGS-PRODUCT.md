# Nix Settings terminal UI

The Rust frontend is ported from `feature/nix-settings-tui`, using the exact
Linutil TUI snapshot at `0b0f7449e79275a7ad5cd1c0dee48c6d71f1f7f1`.
The vendor snapshot and MIT notices remain intact. Adapted application files live
in `nix-settings/crates/`; `pkgs/nix-settings` builds/tests and wraps the package.

## State and architecture

`nx status --json` supplies the configured host, repository, generation and enabled
features. `nx` and `nixctl` share `/etc/nixctl.conf`, generated from `my.repoPath`.
An explicit NX_CONF/NIXCTL_CONF override must point to the same file for both tools.
A failed status read stops startup before taking over the terminal.

The application keeps Linutil's navigation, search, themes, confirmation modal and
PTY output. Configuration opens the existing nixctl feature/compositor/kernel
selectors inside that PTY. There is no `state/<host>.json`, generated profile matrix
or second feature parser. `hosts/<host>/features.nix` is the source of truth.
Gaming controls the complete gaming module, including the Eden Nix package.
Unsupported old browser/Filen/bundle controls are not presented as working switches.

Actions are explicit program/argument lists. Updates use nx's lock transaction,
build-first flow and activation confirmation. Normal updates do not commit or push.
Dotfile synchronization delegates to dots; user-profile packages remain separate.
The terminal is restored on success and on initialization/runtime errors.

## Entry points

```sh
nix run github:madebycli/nix-config#nix-settings
nix-settings-tui
nix-settings-tui --status-json
nixctl kernel                 # standard latest or optional CachyOS
```

`nix-settings-tui` is an unambiguous alias for the Rust app; the separate GTK
project also uses the name `nix-settings`. The Noctalia plugin opens the Rust alias.

## Verification

```sh
cd nix-settings
cargo fmt --all --check
cargo test --workspace --locked
cd ..
python3 tests/nixctl_test.py
nix build --no-link .#nix-settings .#nixctl
NIX_SETTINGS_BINARY=$(nix build --no-link --print-out-paths .#nix-settings)/bin/nix-settings-tui python3 tests/nix_settings_test.py
```

CLI tests use temporary repos/configs and read-only status. The terminal test
starts the actual Rust binary in a controlling PTY and verifies first rendering,
quit and restoration. Real desktop appearance, sudo prompts and an actual
build/switch still require acceptance on Nyx/Aether.
