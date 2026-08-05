# Nix maintenance commands

This configuration separates repository updates, Flake input updates, personal Nix profiles, and NixOS system generations.

## Commands

| Command | Purpose |
|---|---|
| `config-update` | Pull newer configuration commits, build, and activate |
| `nix-help` | Show the command overview |
| `nix-status [--online]` | Show system, store, Git, and profile status |
| `nix-updates [MODE] [--full]` | Preview Flake and profile updates |
| `nix-refresh [MODE]` | Update selected sources, build, and activate |
| `nix-generations` | List or compare NixOS system generations |
| `nix-clean [1-20]` | Keep the running generation plus a selected number of backups |
| `nix-optimize` | Deduplicate identical Nix Store files |
| `nix-rollback` | Switch to the previous NixOS system generation |

## Update modes

| Mode | Flake inputs | Personal profile |
|---|---|---|
| `nix-refresh` | all inputs | update |
| `nix-refresh base` | `nixpkgs`, `nix-cachyos-kernel` | update |
| `nix-refresh packages` | `nixpkgs` | update |
| `nix-refresh kernel` | `nix-cachyos-kernel` | unchanged |
| `nix-refresh desktop` | `home-manager`, `mango`, `noctalia`, `noctalia-greeter` | unchanged |
| `nix-refresh profiles` | none | update |

Personal profile updates use:

```bash
nix profile upgrade --all --refresh
```

## Update preview

```bash
nix-updates
nix-updates base
nix-updates desktop
nix-updates profiles
nix-updates --full
```

Flake updates are resolved in a temporary repository copy. Personal profile updates are applied to a temporary copy of the profile and compared with the current profile. `--full` also builds the candidate NixOS system closure and runs `nix store diff-closures`.

## Generations

```bash
nix-generations
nix-generations --last 10
nix-generations --diff 21 22
```

## Cleanup

```bash
nix-clean --dry-run 5
nix-clean 5
```

The number is the count of rollback generations kept in addition to the running generation. The default is five. Cleanup refuses to run when the running system differs from the boot default or is not the newest generation.

## Store optimization

```bash
nix-optimize
```

This runs `nix-store --optimise -vv` and reports the measured store size before and after.
