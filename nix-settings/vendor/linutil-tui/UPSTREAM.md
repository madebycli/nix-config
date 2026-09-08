# Linutil TUI upstream snapshot

Source: https://github.com/ChrisTitusTech/linutil
Commit: `0b0f7449e79275a7ad5cd1c0dee48c6d71f1f7f1`
License: MIT
Copyright: Copyright (c) 2025 Chris Titus

`src/`, `assets/`, `Cargo.toml`, and `cool_tips.txt` are copied from the
upstream TUI at the commit above. They are intentionally kept as an exact
reference snapshot. Nix Settings directly compiles selected upstream modules
(theme, hints, floating-window primitives, confirmation prompt, and system
information) and keeps adapted derivative files separate under `crates/tui`.
