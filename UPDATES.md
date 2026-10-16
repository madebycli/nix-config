# Updating and housekeeping with `nx`

One command replaces the old `config-update` and `nix-*` scripts. Every read
command has `--json` (used by the Noctalia plugin).

| Command | What it does |
|---|---|
| `nx status` | host, generation, repository state, enabled features, cached update state (offline, instant) |
| `nx check` | which inputs have updates; **about 2 seconds**, only `git ls-remote`, nothing is built or downloaded |
| `nx pull` | fetch the repository and fast-forward (never merges) |
| `nx switch` | build this host, show the closure diff, activate after confirmation |
| `nx update` | update only the outdated inputs, build, show the diff, activate after confirmation |
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
nx update                 # update every outdated input, build, diff, confirm, switch
nx update base            # nixpkgs + CachyOS kernel
nx update desktop         # home-manager, mango, caelestia-shell
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
- a `flake.lock` that already has uncommitted changes stops the update;
- after a successful switch the lock is committed (`--no-commit` to skip, `--push` to push).

Nixpkgs, Noctalia and the Noctalia Greeter all come from the `nixpkgs` input, so
`nx update base` updates them together. Groups: `base` = nixpkgs, nix-cachyos-kernel;
`desktop` = home-manager, mango, caelestia-shell; `apps` = microvm.

## Features and desktop

Desktop and feature selection is `hosts/<host>/features.nix`, changed with `nixctl`
(`nixctl desktop`, `nixctl on ai`, `nixctl apply`).

## Generations and cleanup

```bash
nx gen --last 10
nx gen diff 41 43
nx clean --dry-run 5
nx clean 5
nx rollback
```

`nx clean` never deletes the next-boot, running or booted generation.
