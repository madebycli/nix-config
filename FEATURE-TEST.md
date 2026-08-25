# Hyprland + Caelestia feature test

This branch is isolated from `main` and is intended for testing the new desktop matrix.

## Nyx quick start (Fish)

From the existing `~/nyx` repository:

```fish
cd ~/nyx

git fetch origin

if git show-ref --verify --quiet refs/heads/feature/hyprland-caelestia
    git switch feature/hyprland-caelestia
else
    git switch --track -c feature/hyprland-caelestia origin/feature/hyprland-caelestia
end

git pull --ff-only

git ls-files -v hosts/nyx/hardware-configuration.nix
```

The hardware file should start with `S`, which means the local real hardware configuration remains protected with `skip-worktree`.

## Build before switching

Hyprland + Noctalia:

```fish
sudo nixos-rebuild build --flake .#nyx-hyprland
```

Hyprland + Caelestia Shell:

```fish
sudo nixos-rebuild build --flake .#nyx-hyprland-caelestia
```

The Caelestia profile uses the checked-in Flake input and `caelestia-shell.packages.x86_64-linux.with-cli`. It does not use `nix run` to install Caelestia.

## Activate Hyprland + Caelestia

Only after the build succeeds:

```fish
sudo nixos-rebuild switch --flake .#nyx-hyprland-caelestia
```

Then reboot or log out and choose the Hyprland session from the greeter.

## Other profiles

```text
nyx                         Mango + Noctalia
nyx-mango                   Mango + Noctalia
nyx-niri                    Niri + Noctalia
nyx-hyprland                Hyprland + Noctalia
nyx-hyprland-caelestia      Hyprland + Caelestia Shell
nyx-mango-niri              Mango + Niri + Noctalia
nyx-mango-hyprland          Mango + Hyprland + Noctalia
nyx-niri-hyprland           Niri + Hyprland + Noctalia
nyx-all                     Mango + Niri + Hyprland + Noctalia
```

The same profile suffixes exist for `aether`.

## Return to main

```fish
cd ~/nyx
git switch main
git pull --ff-only
```

Do not delete the local hardware configuration. The branch switch is safe only while `hosts/nyx/hardware-configuration.nix` remains protected with `skip-worktree`.
