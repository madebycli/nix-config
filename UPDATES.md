# Updating and housekeeping with `nx`

One command replaces the old `config-update` and `nix-*` scripts. Every read
command has `--json` for scripts and other tools.

| Command | What it does |
|---|---|
| `nx status` | host, generation, repository state, enabled features, cached update state (offline, instant) |
| `nx check` | which inputs have updates; **about 2 seconds**, only `git ls-remote`, nothing is built or downloaded |
| `nx pull` | fast-forward repository code and reconcile the saved local lock with Nix |
| `nx switch` | build this host, show the closure diff, activate after confirmation |
| `nx update` | refresh all inputs in the local lock, build, show the diff, activate after confirmation |
| `nx gen` / `nx gen diff A [B]` | list generations / compare two |
| `nx rollback` | switch back to the previous generation |
| `nx clean [N]` | delete old generations (keeps the newest N+1 plus selected, running and booted) and free the store |
| `nx optimise` | deduplicate identical store files |

## Why `nx check` is fast

The old preview resolved every update in a temporary copy of the repository and
could build the candidate system. `nx check` instead compares the revision in
`flake.lock` with the upstream branch head (`git ls-remote`, 12 in parallel,
10 s timeout each). That answers "is there an update?" without evaluating or
downloading anything. Use `nx update --build` to see what an update would
change, without activating it.

## Updating

```bash
nx check                  # what is outdated?
nx update                 # refresh every input, build, diff, confirm, switch
nx update base            # nixpkgs + CachyOS kernel
nx update desktop         # home-manager, mango, noctalia, caelestia-shell
nx update apps            # microvm
nx update mango nixpkgs   # specific inputs
nx update all             # every input
nx update --profiles      # also `nix profile upgrade --all`
nx update --build         # build and diff only, flake.lock is restored
nx update --boot -y       # activate on next boot, no question
```

Safety rules (unchanged in spirit from the old tools):

- the system is built **before** anything is activated;
- `flake.lock` is restored if the update, the build or your confirmation fails;
- existing local lock updates are kept as the starting point; no commit is required;
- normal updates never commit or push and do not require a Git identity or GitHub login;
- `--commit` explicitly commits the lock after activation; `--push` explicitly commits and pushes;
- Git identity is checked before an update that requests a commit; `--no-commit` remains a compatibility option.

## Pulling code after local updates

`nx pull` keeps a changed local `flake.lock` out of Git's text merge. It saves a
backup under Git's `nx/lock-backups` directory, fast-forwards the code, restores
the local lock, then runs `nix flake lock`. Nix preserves local versions for
unchanged input declarations and reconciles changed, added or removed inputs.
Remote lock-only version changes do not replace your local choices; `nx update`
refreshes those from upstream. Local lock changes are left uncommitted.

Other local files still use Git autostash. Unresolved conflicts stop the command
with an error and are never discarded. If lock reconciliation fails, the original
local lock is restored and the backup is retained; retry with `nx update`.
No system is built or activated by `nx pull`.

The public HTTPS installation needs no GitHub login. Before evaluation and build,
the installer refreshes every flake input, including on a clean installation. It
keeps the new local lock after activation and restores the previous lock on
failure or cancellation. Fresh installs therefore resolve current upstream
versions rather than relying only on the repository's committed lock.

The Noctalia shell comes from its own upstream `noctalia` flake input, without
an additional binary cache. `nx update noctalia` or `nx update desktop` updates
the shell. The Noctalia Greeter stays in `nixpkgs` and updates with `nx update base`.
Groups: `base` = nixpkgs, nix-cachyos-kernel; `desktop` = home-manager, mango,
noctalia, caelestia-shell; `apps` = microvm.

## Features and desktop

Desktop and feature selection is `hosts/<host>/features.nix`, changed with `nixctl`
(`nixctl desktop`, `nixctl kernel`, `nixctl on ai`, `nixctl apply`).
The CLI selectors preserve nx confirmation and local-lock recovery.
The experimental Settings frontend and native panel are kept on the
`feature/settings-sandbox` branch.

## Generations and cleanup

```bash
nx gen --last 10
nx gen diff 41 43
nx clean --dry-run 5
nx clean 5
nx rollback
```

`nx clean` never deletes the next-boot, running or booted generation.
