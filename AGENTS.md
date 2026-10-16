# Guidelines for AI assistants

Read `.ai/CONTEXT.md` first; it routes to the private project context.

## Layout

```
flake.nix            inputs, hosts, packages, dev shells (keep it small)
modules/core/        always-on system modules (base, storage, home-manager, tools)
modules/desktop/     compositors, shells, greeter, GPU drivers (my.desktop.*)
modules/features/    optional features, each behind my.features.<name>.enable
hosts/<host>/        default.nix (hardware facts), features.nix (switches)
pkgs/                commands (nx, gbox, dots, nixctl, agentbox, plmf) and themes
config/<app>/        app configuration synchronised by `dots`
tests/               shell/VM tests; CI runs them
```

## Rules

- New optional functionality is a module in `modules/features/` with an
  `enable` option; hosts switch it on in `hosts/<host>/features.nix` using
  one `my.features.<name>.enable = <bool>;` line per feature (nixctl edits
  those lines by regex, keep the format).
- Small commands go in `pkgs/<name>/` as `<name>.sh` plus `default.nix` using
  `writeShellApplication` (shellcheck must pass). `nx` is Python (stdlib only) with
  unit tests in `tests/nx_test.py`; keep its read commands scriptable (`--json`).
- `hosts/*/hardware-configuration.nix` in Git are empty placeholders; the installer
  copies the machine's own file over them and marks them `skip-worktree`. Never
  commit real hardware data.
- Caelestia only with `my.desktop.compositors = [ "hyprland" ]` (asserted).
- No secrets, tokens or private keys in the repository.

## Checks before calling a change done

```bash
nix eval --raw .#nixosConfigurations.ci-nyx.config.system.build.toplevel.drvPath
nix eval --raw .#nixosConfigurations.ci-aether-full.config.system.build.toplevel.drvPath
nix build .#nx .#gbox .#dots .#nixctl .#agentbox
bash tests/plmf-cli-test.sh
python3 tests/nx_test.py
DOTS=$(nix build .#dots --print-out-paths --no-link)/bin/dots bash tests/dots-test.sh
```

`ci-<host>` and `ci-<host>-full` are evaluation-only stand-ins with a fake root
file system; the real hosts need their own hardware file.
