# Update commands

This configuration separates repository changes from flake-input updates. Every command detects `nyx` or `aether` automatically and expects the repository remote to be either `https://github.com/madebycli/nix-config.git` or `git@github.com:madebycli/nix-config.git`.

## Commands

| Command | Effect |
|---|---|
| `config-update` | Pull newer configuration files, build, and activate them |
| `system-update` | Update every flake input, build, and activate the result |
| `system-update base` | Update Nixpkgs and the CachyOS kernel input |
| `system-update packages` | Update Nixpkgs and the madebycli application catalog |
| `system-update kernel` | Update only the CachyOS kernel input |
| `system-update desktop` | Update Home Manager, Mango, Noctalia, and Noctalia Greeter |
| `system-rollback` | Switch to the previous NixOS system generation |

## Input groups

### All

```text
nixpkgs
nix-pkgs
home-manager
nix-cachyos-kernel
mango
noctalia
noctalia-greeter
```

### Base

```text
nixpkgs
nix-cachyos-kernel
```

### Packages

```text
nixpkgs
nix-pkgs
```

The `nix-pkgs` input provides the system-managed Helium Browser package and TwintailLauncher NixOS module.

### Kernel

```text
nix-cachyos-kernel
```

### Desktop

```text
home-manager
mango
noctalia
noctalia-greeter
```

## `system-update` transaction

1. Detect the host and the most recently selected desktop profile.
2. Check whether GitHub contains newer configuration code.
3. Back up the current `flake.lock`.
4. Request administrator credentials once and keep the sudo timestamp alive.
5. Refresh only the selected flake inputs.
6. Build the complete NixOS system.
7. Switch only after the build succeeds.
8. Schedule a one-time TRIM pass for the next boot.
9. Commit and push the tested `flake.lock` when the Git state and identity allow it.

When input resolution or the build fails before activation, the previous lock file is restored automatically. Other local files are not modified.

When GitHub contains newer configuration code, `system-update` stops and asks you to run `config-update` first.

## Rollback

```bash
system-rollback
```

This executes:

```bash
sudo nixos-rebuild switch --rollback
```

The running system and boot default return to the previous NixOS generation. The repository and `flake.lock` remain unchanged. Restart after a kernel or initrd rollback.

## Activating the commands after an existing installation

```bash
config-update
```

After the new configuration is activated, `system-update` and `system-rollback` are available directly in the terminal.
