# Config Sync with GitHub CLI

Config Sync uses a hybrid design:

- **GitHub CLI (`gh`) owns authentication.** Browser sign-in, credential storage, account discovery and repository permission checks are delegated to GitHub CLI.
- **Git owns repository transactions.** Diff, staging, commits, fetch, fast-forward merge and push remain normal Git operations.
- **The existing three-way dotfile model remains authoritative.** HOME, `config/home`, and the last successful sync state are compared by content hash. Conflicts are never resolved by timestamps.

## Why not `gh repo sync`?

`gh repo sync` synchronizes repository branches. Config Sync has additional local state and must distinguish NixOS repository files from versioned HOME files, preserve selective backups, block secret-like files, and refuse overlapping local/remote edits. Replacing that logic with `gh repo sync` would discard those safety properties.

## Login

Nix Settings starts GitHub CLI's supported browser flow:

```text
gh auth login --hostname github.com --web --git-protocol https
```

After approval it runs:

```text
gh auth setup-git --hostname github.com
```

Nix Settings never asks for, reads, logs, or stores the GitHub token. GitHub CLI owns its credential storage.

The accepted legacy SSH origin is normalized to:

```text
https://github.com/madebycli/nix-config.git
```

before authenticated uploads. Existing unrelated remotes are rejected.

## Git identity

If the repository has no local `user.name` or `user.email`, Config Sync derives them from the authenticated GitHub account. When GitHub does not expose a public email address, a GitHub noreply address is used. Existing repository-local identity settings are preserved.

## Permissions

Upload and Synchronize require the authenticated account to have `WRITE`, `MAINTAIN`, or `ADMIN` permission on `madebycli/nix-config`.

Read-only status and Download remain usable without a GitHub login because the repository is public.

## Synchronization rules

Before a fast-forward, local repository paths are compared with the paths changed by the incoming commits. Disjoint local changes are preserved. Overlapping paths abort before the merge.

For managed dotfiles, the existing content-hash classifier still distinguishes:

- local-only changes;
- repository-only changes;
- identical changes;
- true three-way conflicts.

Remote dotfile changes are backed up before they replace local files. Secret-like filenames, symlinks, unsafe managed paths, staged leftovers, and diverged Git history remain blocking conditions.

## Noninteractive GUI behavior

GUI actions use `--yes`. A default timestamped commit message is generated automatically when none is supplied, so the GUI never blocks on a hidden terminal prompt.

System activation remains separate from Config Sync in Nix Settings: GUI Download/Synchronize pass `--no-apply`. Pulling configuration therefore cannot silently switch the running NixOS generation.
