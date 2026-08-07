# Nix Settings machine-readable API

This document describes the read-only contracts consumed by `madebycli/nix-settings`.
The existing terminal output remains the default.

## `nix-status --json`

Returns one JSON object with `schemaVersion: 1`. Fields include host/profile,
system generation counts, byte-accurate store/closure/disk values, repository
state, personal profile count, last successful config sync, refresh time, and a
non-fatal `errors` array. `--online` may be combined with `--json` to fetch the
configured origin before calculating ahead/behind.

## `nix-updates MODE --json`

Runs the existing safe preview in temporary repository/profile copies. It never
changes the real `flake.lock` or personal profile. Supported modes and sources:

- `all`: nixpkgs, home-manager, nix-cachyos-kernel, mango, noctalia,
  noctalia-greeter, personal profiles
- `base`: nixpkgs, nix-cachyos-kernel, personal profiles
- `packages`: nixpkgs, personal profiles
- `kernel`: nix-cachyos-kernel
- `desktop`: home-manager, mango, noctalia, noctalia-greeter
- `profiles`: personal profiles

The result includes repository relation, one stable source object per selected
input, profile summary, optional closure preview, and errors. `--full` is
explicit and may perform an expensive build in the temporary copy.

## `nix-generations --json`

Returns current/latest generation metadata and a structured generation list.
`--last COUNT` may be combined with `--json`.

## `nix-clean --dry-run COUNT --json`

Returns the exact protected current/latest generation, backup count, and the
proposed deletion set. JSON is intentionally unavailable for a destructive run;
callers must preview first and use the restricted privileged helper for the
confirmed operation.

## `scripts/config-sync-json.py`

Read-only adapter over the existing `config-sync.py` implementation. It imports
and reuses repository discovery, remote validation, manifests, checksums, secret
checks, conflict classification, state and locking concepts. Commands:

- `status --scope all|nixos|dotfiles`
- `paths`
- `doctor`

It does not copy, commit, pull, push, apply, or resolve conflicts.

## Compatibility and safety

- Text output remains the default for terminal users.
- JSON objects are UTF-8 and contain no ANSI terminal escapes.
- Preview commands do not mutate the real lock file or profile.
- Conflicts are reported; no date-based winner is selected.
- New fields may be added within a schema version. Existing fields are stable.
