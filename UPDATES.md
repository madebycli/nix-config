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

## Desktop inputs

Desktop-related Flake inputs are:

```text
home-manager
mango
noctalia
noctalia-greeter
hyprland
caelestia-shell
```

Caelestia Shell is integrated through the normal Flake input:

```nix
caelestia-shell = {
  url = "github:caelestia-dots/shell";
  inputs.nixpkgs.follows = "nixpkgs";
};
```

The Hyprland + Caelestia profile uses the upstream Home Manager module with `caelestia-shell.packages.<system>.with-cli`.

## Update modes

| Mode | Flake inputs | Personal profile |
|---|---|---|
| `nix-refresh` | all inputs | update |
| `nix-refresh base` | `nixpkgs`, `nix-cachyos-kernel` | update |
| `nix-refresh packages` | `nixpkgs` | update |
| `nix-refresh kernel` | `nix-cachyos-kernel` | unchanged |
| `nix-refresh desktop` | Home Manager plus all compositor and shell inputs | unchanged |
| `nix-refresh profiles` | none | update |

`nix-refresh desktop` updates:

```text
home-manager
mango
noctalia
noctalia-greeter
hyprland
caelestia-shell
```

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

The `all` and `desktop` preview modes include both Hyprland and Caelestia Shell even when the currently active profile does not use them. This keeps every declared desktop source visible and updateable.

## Desktop profile selection

The installer and `config-update` support combinable compositor flags:

```text
--mango
--niri
--hyprland
```

Shell flags are separate:

```text
--noctalia
--caelestia-shell
```

No selection means Mango + Noctalia. `--all` selects Mango + Niri + Hyprland with Noctalia. Caelestia Shell is restricted to the Hyprland-only profile.

Examples:

```bash
config-update --niri --noctalia
config-update --mango --niri --noctalia
config-update --hyprland --noctalia
config-update --hyprland --caelestia-shell
config-update --all
```

Without selection flags, `config-update` reuses the last saved profile when available.

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
