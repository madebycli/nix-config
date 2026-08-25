<p align="center">
  <img src="assets/readme-banner.svg" alt="NixOS Multi-Host Configuration" width="100%">
</p>

<p align="center">
  <img alt="NixOS unstable" src="https://img.shields.io/badge/NixOS-unstable-5277C3?logo=nixos&logoColor=white">
  <img alt="Nix flakes" src="https://img.shields.io/badge/Nix-Flakes-7EBAE4?logo=nixos&logoColor=white">
  <img alt="Home Manager" src="https://img.shields.io/badge/Home_Manager-enabled-4A90E2">
  <img alt="Desktop" src="https://img.shields.io/badge/Desktop-Mango_%2B_Niri_%2B_Hyprland-8A2BE2">
</p>

<p align="center">
  Reproducible NixOS systems for two machines, with safe installation, transactional updates, selectable Wayland compositors and shells, and local hardware protection.
</p>

## Systems

| Host | Hardware | Optimization | Default desktop |
|---|---|---|---|
| `nyx` | AMD desktop | `znver4` | Mango + Noctalia |
| `aether` | Intel/NVIDIA laptop | `x86-64-v3` with NVIDIA PRIME | Mango + Noctalia |

Mango, Niri, and Hyprland can be selected individually or combined. Noctalia is the default desktop shell. Caelestia Shell is an opt-in Hyprland-only shell profile.

## Highlights

- Multi-host NixOS flake with shared modules and host-specific hardware definitions
- Mango, Niri, and Hyprland compositor profiles
- Noctalia as the default shell and Caelestia Shell as an optional Hyprland shell
- Noctalia Greeter and Home Manager integration
- CachyOS kernel integration with a configured binary cache
- Native Flatpak integration
- Safe local handling of `hardware-configuration.nix`
- Build-before-switch installation and update flow
- Automatic lock-file recovery when an input update or build fails
- LUKS tuning and a one-time TRIM pass after successful system changes
- Manual, versioned synchronization for Mango, Niri, Noctalia, and Caelestia dotfiles
- Integrated status, update preview, generation cleanup, optimization, and rollback tools
- Companion application catalog through [`madebycli/nix-pkgs`](https://github.com/madebycli/nix-pkgs)

## Fresh installation or reinstall

Start from a normal minimal NixOS installation with networking, Git, Nix, `sudo`, and `/etc/nixos/hardware-configuration.nix` available. The installer expects the configured user account to be named `xxxxx`.

### Nyx

```bash
nix run --refresh github:madebycli/nix-config#install -- --nyx
```

### Aether

```bash
nix run --refresh github:madebycli/nix-config#install -- --aether
```

The default profile is **Mango + Noctalia**. Compositor flags can be combined, while the shell is selected separately:

```text
--mango
--niri
--hyprland
--all
--noctalia
--caelestia-shell
```

Examples:

```bash
# Default: Mango + Noctalia
nix run --refresh github:madebycli/nix-config#install -- --nyx

# Niri + Noctalia
nix run --refresh github:madebycli/nix-config#install -- --nyx --niri --noctalia

# Mango + Niri + Noctalia
nix run --refresh github:madebycli/nix-config#install -- --nyx --mango --niri --noctalia

# Hyprland + Noctalia
nix run --refresh github:madebycli/nix-config#install -- --nyx --hyprland --noctalia

# Hyprland + Caelestia Shell
nix run --refresh github:madebycli/nix-config#install -- --nyx --hyprland --caelestia-shell

# Mango + Niri + Hyprland, using Noctalia
nix run --refresh github:madebycli/nix-config#install -- --nyx --all
```

`--both` no longer exists. `--all` means all three compositors with Noctalia. Caelestia Shell is intentionally restricted to the Hyprland-only profile because Caelestia is designed around Hyprland.

The installer clones or safely fast-forwards the correct repository, copies only the selected host's hardware configuration, protects it with `skip-worktree`, evaluates and builds before switching, initializes managed dotfiles, and schedules a one-time TRIM pass for the next boot.

## Hyprland

Hyprland uses the native NixOS and Home Manager modules from the pinned Nixpkgs/Home Manager inputs. There is no separate Hyprland Flake input. The NixOS module installs Hyprland and its portal; Home Manager only writes the user configuration.

## Caelestia Shell

Caelestia is integrated as a normal Flake input, not through `nix run`:

```nix
caelestia-shell = {
  url = "github:caelestia-dots/shell";
  inputs.nixpkgs.follows = "nixpkgs";
};
```

The Hyprland + Caelestia profile uses the upstream Home Manager module and explicitly selects:

```nix
inputs.caelestia-shell.packages.${system}.with-cli
```

This provides the full shell plus CLI from the same locked Flake input.

## Nix command suite

Run the built-in overview:

```bash
nix-help
```

The commands are standalone programs with a hyphen. They do not replace or wrap official commands such as `nix shell` or `nix profile`.

| Command | Purpose |
|---|---|
| `nix-status` | TUI-like overview of generations, Nix Store, closure, disk, Git, and profile packages |
| `nix-updates` | Preview all selected Flake and personal profile updates without touching the real lock file |
| `nix-refresh` | Update Flake inputs, build, switch, and update personal profile packages where configured |
| `nix-generations` | List NixOS system generations or compare two closures |
| `nix-clean` | Keep the current generation plus a chosen number of rollback generations |
| `nix-optimize` | Deduplicate identical files in the Nix Store without deleting generations |
| `nix-rollback` | Switch to the previous NixOS system generation |
| `nix-help` | Show the complete command overview |

Common examples:

```bash
nix-status --online
nix-updates
nix-updates --full
nix-refresh
nix-refresh base
nix-refresh desktop
nix-generations
nix-clean --dry-run 5
nix-clean 5
nix-optimize
nix-rollback
```

`nix-refresh`, `nix-refresh base`, and `nix-refresh packages` also run:

```bash
nix profile upgrade --all --refresh
```

`nix-refresh desktop` updates Home Manager, Mango, Noctalia, Noctalia Greeter, and Caelestia Shell. Hyprland comes from Nixpkgs and is therefore updated by `nix-refresh`, `nix-refresh base`, or `nix-refresh packages`. The desktop mode does not update Nixpkgs, the CachyOS kernel, or personal profile packages. See [UPDATES.md](UPDATES.md) for the exact groups and safety behavior.

Pull newer configuration code from GitHub without changing the input set:

```bash
config-update
```

`config-update` accepts the same compositor and shell selection flags as the installer. Without selection flags it reuses the last saved profile when available.

## Application catalog

Desktop applications and terminal tools maintained outside this system configuration are collected in [`madebycli/nix-pkgs`](https://github.com/madebycli/nix-pkgs).

```bash
nix profile add github:madebycli/nix-pkgs#<package>
nix profile upgrade --all --refresh
```

Profile-managed packages and system-managed Flake inputs remain separate Nix profiles, but the appropriate `nix-refresh` modes update both in one guided workflow.

## Desktop profiles

Noctalia is the standard shell for every compositor combination. Caelestia is available only with Hyprland alone.

| Selection | Nyx profile | Aether profile | Shell |
|---|---|---|---|
| Default / Mango | `nyx` | `aether` | Noctalia |
| Niri | `nyx-niri` | `aether-niri` | Noctalia |
| Hyprland | `nyx-hyprland` | `aether-hyprland` | Noctalia |
| Hyprland + Caelestia | `nyx-hyprland-caelestia` | `aether-hyprland-caelestia` | Caelestia |
| Mango + Niri | `nyx-mango-niri` | `aether-mango-niri` | Noctalia |
| Mango + Hyprland | `nyx-mango-hyprland` | `aether-mango-hyprland` | Noctalia |
| Niri + Hyprland | `nyx-niri-hyprland` | `aether-niri-hyprland` | Noctalia |
| All compositors | `nyx-all` | `aether-all` | Noctalia |

The explicit `nyx-mango` and `aether-mango` aliases remain available and are equivalent to the default Mango + Noctalia profile.

## Configuration tools

| Command | Purpose |
|---|---|
| `config-update` | Pull configuration changes, build, and optionally activate them |
| `config-sync` | Compare, pull, push, or synchronize managed configuration files |
| `save-config` | Save selected local configuration changes into the repository mirror |
| `script-update` | Review and replace maintained helper scripts safely |

Managed user configuration currently covers:

```text
~/.config/mango
~/.config/niri
~/.config/noctalia
~/.config/caelestia
```

Hyprland's initial configuration is declarative through Home Manager. Caelestia uses its upstream Home Manager module and keeps its own runtime configuration under `~/.config/caelestia` when customized.

## Hardware and update safety

Real hardware files are never sourced from GitHub during installation. The installer copies `/etc/nixos/hardware-configuration.nix` into the selected host directory and marks the tracked placeholder as `skip-worktree` locally.

System changes validate the expected repository and remote, refuse unsafe or diverged Git states, preserve local hardware data, build before switching, restore the previous lock file after failures before activation, and keep timestamped local backups where replacement is necessary.

`nix-clean` changes only the NixOS system profile. By default it protects the running generation plus five rollback generations. It refuses to run when the running system and boot default differ or when a newer generation exists, and always supports `--dry-run`.

Automatic weekly garbage collection removes only already-unreachable store paths. Generation retention is controlled explicitly through `nix-clean`, while automatic weekly store optimization remains enabled.

## Repository layout

```text
flake.nix                 host profiles, applications, and command suite
hosts/                    nyx and aether definitions
modules/nixos/            shared NixOS modules and compositor modules
modules/home/             Home Manager and Hyprland user configuration
modules/flatpak/          Flatpak integration
scripts/                  installer, Nix tools, updater, and sync tools
sync/                     managed path declarations
config/home/              versioned user-configuration mirror
```

This repository contains personal machine configuration. Host-specific hardware data, generated system state, credentials, and private user data must remain local.
