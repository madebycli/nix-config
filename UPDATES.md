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
| `nx update profiles` | upgrade only user-profile packages, without reading or building the system flake |
| `nx profiles` | list every package in the default Nix user profile |
| `nx debug` | detailed local diagnostics, findings, logs and redacted text/JSON reports |
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
nx update desktop         # home-manager, mango, nixpkgs (Noctalia + Greeter), caelestia-shell
nx update apps            # microvm
nx update mango nixpkgs   # specific inputs
nx update noctalia        # alias: update nixpkgs for the Noctalia shell + Greeter
nx update noctalia-greeter # alias: update nixpkgs for the Greeter + shell
nx update all             # every input
nx update --profiles      # also `nix profile upgrade --all`
nx update profiles        # only user-profile packages; no system rebuild
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

The former upstream `noctalia` flake input is disabled. Both `noctalia` and
`noctalia-greeter` are installed from the root `nixpkgs` input tracking
`nixos-unstable`. `nx update noctalia`, `nx update noctalia-greeter`,
`nx update desktop` and `nx update base` all update that same Nixpkgs input.
This also updates other Nixpkgs packages, not just Noctalia. Versions remain
pinned by `flake.lock` until the input is updated. No extra cache is configured.
Groups: `base` = nixpkgs, nix-cachyos-kernel; `desktop` = home-manager, mango,
nixpkgs, caelestia-shell; `apps` = microvm.

## Features and desktop

Desktop and feature selection is `hosts/<host>/features.nix`, changed with `nixctl`
(`nixctl desktop`, `nixctl kernel`, `nixctl on ai`, `nixctl apply`).
The CLI selectors preserve nx confirmation and local-lock recovery.
The experimental Settings frontend and native panel are kept on the
`feature/settings-sandbox` branch.

## User-profile packages

`nx profiles` manages packages installed with `nix profile`. These are independent
of the Gaming/Desktop feature switches and declarative system/Home Manager packages.
The commands work without `/etc/nixctl.conf` or a nix-config checkout, and never
run a NixOS rebuild, use sudo or commit a system lock.

```bash
nx profiles                         # same as: nx profiles list
nx profiles list --json              # package names, sources and store paths
nx profiles install nixpkgs#hello    # add a package
nx profiles remove hello            # exact name from the list
nx profiles update                  # upgrade every package in this profile
nx profiles update hello            # upgrade one or more exact names
nx update profiles                  # same as: nx profiles update
nx profiles history                 # native history of package changes
nx profiles rollback                # previous profile generation
nx profiles rollback 7              # a specific profile generation
nx profiles --profile ~/tools list  # explicitly select another profile
nx update profiles --profile ~/tools
```

Mutations show/confirm their target; `--yes` skips confirmation for scripts.
An empty profile is a no-op. Removing packages accepts exact listed names, not
wildcards, and does not delete old generations or garbage-collect the store.
Aliases: `ls`, `add`, `rm` and `upgrade`.

The list includes all sources (GitHub, GitLab, local flakes and direct store
paths). Nix decides which entries can be upgraded; explicitly pinned references
and direct store paths do not acquire a new version automatically. The lightweight
`nx check --profiles` upstream revision probe still covers GitHub-based entries.

`--profile PATH` works before or after the `nx profiles` action. Omitting it
delegates profile selection to Nix. `list --json` returns a `packages` array;
`history --json` returns Nix's native history text in the `history` field.
Profile install/update passes `--no-write-lock-file`, preserving source flake locks.

`nx update --profiles` and `nx update desktop profiles` update the system and
profile together, using one confirmation. A profile upgrade failure is reported
as an error; an already activated system is retained. Profile-only updates reject
system-only `--build`, `--boot`, `--commit` and `--push` options.

## Diagnostics and support reports

`nx debug` collects local evidence without building, evaluating a flake, activating
a system, changing settings, repairing services or requesting sudo. It works
without nx configuration and continues when a tool, file, service, journal or
permission is missing. Tools already on PATH are used; no extra packages or
background services are installed for diagnostics. Local Nix read commands can
use Nix's normal internal metadata caches.

```bash
nx debug                                      # all normal sections
nx debug --list                               # available diagnostic sections
nx debug nix cache repo                        # focus on installation/update issues
nx debug --full                                # more hardware, service and log detail
nx debug services --unit greetd.service         # properties and bounded unit journal
nx debug services --user-unit pipewire.service  # user service details and journal
nx debug logs --boot -1 --lines 200              # previous boot warnings
nx debug repo --repo ~/nix-config --host nyx     # explicit checkout/host
nx debug profiles --profile ~/tools             # another user profile
nx debug --full --json --output ~/nx-debug.json # private report file, no upload
nx debug nix cache --strict                     # nonzero for findings/incomplete checks
```

| Section | Evidence |
|---|---|
| `system` | OS/kernel, uptime, load, memory and pressure, free bytes/inodes |
| `nix` | Nix version, daemon/socket, allowlisted client/system settings and environment switches |
| `cache` | substitution, signatures, fallback, negative TTL and configured caches |
| `repo` | nx target, Git branch/commit/dirty state, conflicts, lock metadata and host switches |
| `profiles` | all user profile sources, history and system generations |
| `boot` | running/booted/selected system and kernels, boot space and available journal boots |
| `services` | failed system/user units, optional unit properties and journals |
| `hardware` | CPU, PCI/drivers, disks, DRM and audio; full adds USB, modules and NVIDIA |
| `network` | link/NetworkManager/resolver state; no automatic connectivity requests |
| `desktop` | selected session variables, compositor/shell process names, portals/audio |
| `logs` | bounded system/user warnings and Nix daemon journal |
| `build` | an explicitly supplied local store path, derivation dependencies/outputs and saved log |

`build` is selected automatically with `--store-path`. Use a literal store path
from the failed build, including `.drv` when inspecting a derivation:

```bash
nx debug build --store-path /nix/store/HASH-package.drv
nx debug cache --probe-cache
nx debug cache --probe-cache --store-path /nix/store/HASH-package
```

Replace `HASH-package` with the real full store basename (32-character hash).
Build queries are offline with empty substituters. They inspect local metadata
and saved logs; they do not retry a build or fetch a missing log. Derivation
environment/arguments are omitted because they can contain credentials. An absent
local log does not establish build success. Inspect the failing dependency's own
derivation to investigate checks such as the pyrate-limiter test failures.

Only `--probe-cache` sends external requests: bounded HEAD requests to at most
eight configured HTTP(S) substituters, without credentials or redirects. It checks
`nix-cache-info` and, with a non-derivation `--store-path`, that exact output's
narinfo. A 404 means no entry was found at that URL. HEAD failures, denied access
and redirects do not establish availability. Neither a reachable cache nor a
cached output proves all dependencies are cached. Client settings can differ from
daemon settings and per-command overrides; the report makes this limit explicit.

Findings include failed units, repository conflicts, invalid locks, low disk/inode
space, differing selected/running systems or kernels, disabled substitution or
signature checks, and active download fallback. They include next steps where
appropriate. A missing substitute can still trigger a source build with
`fallback=false`; package checks run when enabled by that local derivation.

Each subprocess has an 8-second timeout and 64 KiB each for stdout/stderr.
Collection has a 90-second command budget. Override with `--timeout` (0.1..60),
`--budget` (1..600) and `--max-bytes` (1024..1048576). Reaching a limit stops the
process group, including descendants, and marks the check `timeout`, `truncated`
or `budget-exhausted`. Files are capped at 256 KiB. Journals default to 80 lines
per query, 400 with `--full`; `--lines` allows 1..2000. `--boot` accepts zero or
negative offsets. Repeat `--unit`/`--user-unit` for up to 20 literal unit names.
The full report never treats missing or restricted evidence as a healthy result.

JSON schema version 1 contains timestamp, duration, requested sections, options,
privacy notes, summary counts, findings and section checks. Each command check
records arguments, status, return code, duration and bounded data/output/stderr
when available. Default exit 0 means the report was collected; `--strict` returns
1 for findings or incomplete checks. Invalid arguments and export failures return
nonzero. `--list --json` returns the section description mapping.

Exports use mode 0600 and refuse existing files or symlinks. Reports mask common
credentials/tokens, home/user/hostname identifiers, email and IP/MAC addresses on
a best-effort basis. They omit raw environment, raw NIX_CONFIG, unlisted Nix
settings, process arguments and arbitrary repository file contents. Review before
sharing: domains, device descriptions, paths and log messages can still identify
a system. No report is uploaded automatically.

## Generations and cleanup

```bash
nx gen --last 10
nx gen diff 41 43
nx clean --dry-run 5
nx clean 5
nx rollback
```

`nx clean` never deletes the next-boot, running or booted generation.
