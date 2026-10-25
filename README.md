<p align="center">
  <img src="assets/readme-banner.svg" alt="NixOS Multi-Host Configuration" width="100%">
</p>

<p align="center">
  Reproducible NixOS for two machines. Everything optional is a feature you switch on and off, app configuration syncs through Git with a live switch, updates use nx, and features are selected with nixctl.
</p>

## Systems

| Host | Hardware | Default desktop |
|---|---|---|
| `nyx` | AMD desktop, `znver4` | Mango + Noctalia |
| `aether` | Intel/NVIDIA laptop, PRIME | Mango + Noctalia |

## Install

Start from a minimal NixOS with networking, Git, Nix and `sudo`.

```bash
nix run --refresh github:madebycli/nix-config#install -- --nyx
nix run --refresh github:madebycli/nix-config#install -- --aether
```

The installed system uses the standard NixOS binary cache (`https://cache.nixos.org`).
The CachyOS Attic cache is not configured. Both hosts use the standard Nixpkgs
kernel (`pkgs.linuxPackages_latest`). Missing substitutes are built from source.

The system and installer use NixOS defaults for substitution, signature checking,
download timeouts and fallback. The installer does not override the running
machine's Nix settings. A missing binary substitute may still require a source
build; disabling download fallback does not prohibit source builds.

The installer clones to `~/nix-config`, copies this machine's own
`hardware-configuration.nix` over the tracked placeholder (kept local with
`skip-worktree`, never committed), builds, shows what changes and activates only
after you confirm. Before evaluating or building, it runs `nix flake update` for
all inputs. Failure or cancellation restores the previous lock. Public HTTPS
installation and normal updates require no GitHub login, commit or push.

The default checkout path is `~/nix-config` (`my.repoPath`). If a host uses a
different path, set it in `hosts/<host>/features.nix`, for example
`my.repoPath = "/home/xxxxx/aether";` for an existing Aether checkout, and use
`--dir /home/xxxxx/aether` when installing there.

## Switching features

Each machine's switches live in `hosts/<host>/features.nix`, one line per feature:

```nix
my.features.gaming.enable = true;
my.features.agentbox.enable = false;
```

```bash
nixctl              # interactive list, space toggles, preview, confirm, switch
nixctl on ai        # edit one switch
nixctl desktop      # choose compositors (Mango / Niri / Hyprland) and shell
nixctl kernel       # choose latest or optional CachyOS
nixctl apply        # build, show the closure diff, activate
```

Desktop selection is three options, no per-combination profiles:

```nix
my.desktop.compositors = [ "mango" ];
my.desktop.defaultSession = "mango";
my.desktop.shell = "noctalia";   # "caelestia" only with [ "hyprland" ] alone
```

The Noctalia shell uses the upstream `noctalia` flake input, without an extra
binary cache. The Noctalia Greeter stays in Nixpkgs. `nx update desktop` updates
the shell; `nx update base` updates the greeter.

Both hosts default to Mango only with Noctalia. Their kernel switch is
`my.kernel = "latest";` for the standard `pkgs.linuxPackages_latest` kernel.
CachyOS is temporarily disabled; `"cachyos"` remains available as an explicit
opt-in with the existing host CPU variants. The official NixOS cache is enabled.
The CachyOS Attic cache remains removed. The optional CachyOS input follows
upstream `master`; `nx update base` also updates its locked sources.

| Feature | What it adds |
|---|---|
| `dots` | Git-based sync of app config with a live on/off switch |
| `gaming` | Steam, Proton, Wine, launchers, gamescope and the Eden emulator |
| `virtualisation` | GNOME Boxes, QEMU/KVM, libvirt and VM user permissions |
| `agentbox` | Isolated VM for Claude Code and Codex |
| `plymouth` | Boot splash with themes switchable without a rebuild |
| `ai` | Local models (Ollama, Open WebUI), started on demand |
| `flatpak` | Flatpak with a declarative app list |

The experimental GBox sandbox, Rust Settings frontend and native Nixdatifier
panel are preserved on [feature/settings-sandbox](https://github.com/madebycli/nix-config/tree/feature/settings-sandbox).
Main installs `nixctl` for feature, desktop and kernel selection, and `nx` for
updates and maintenance. If you previously enabled the native panel, disable
Nixdatifier in Noctalia's plugin settings before rebuilding.

## Virtual machines (`virtualisation`)

GNOME Boxes and its host backend are one feature. Enabled on nyx; disabled on
aether until explicitly selected. The CPU vendor is declared with each host's
hardware facts, so only `kvm-amd` (nyx) or `kvm-intel` (aether) is requested.

```bash
nx pull
nixctl on virtualisation
nx switch
```

Reboot once after first enabling this feature to load the selected kernel and
refresh login groups. Then start the native application with `gnome-boxes`.
QEMU/KVM and libvirt come with the feature, including UEFI firmware and virtual
TPM support. System libvirt QEMU guests run as an unprivileged service user.
Boxes normally uses its own `qemu:///session`; it does not share its VM list with
`qemu:///system`. Membership in `libvirtd` also grants system VM administration.
No Docker, GPU passthrough or user-selected VM autostart is configured here.

To disable, shut down VMs and close Boxes first:

```bash
nixctl off virtualisation
nx switch
```

This removes the feature's app, backend configuration and group additions.
Existing VM disks/configurations are preserved; disabling does not delete or
force-stop guests, remove existing Flatpaks, or unload modules already in use.
Agentbox and local-ai remain independent features.

If Boxes still reports **No KVM!**, run these commands as your normal user:

```bash
ls -l /dev/kvm
id
virsh -c qemu:///session capabilities
```

`/dev/kvm` must exist and your current login needs read/write access, normally
through `kvm`. A Ryzen host needs **SVM / AMD-V** enabled in UEFI; an Intel host
needs **VT-x**. Nix cannot enable firmware settings. The generic Boxes message
alone does not identify whether firmware, the driver, permissions or libvirt
caused the failure. If the device is absent after reboot, inspect
`sudo journalctl -b -k --grep='kvm|svm|vmx'`. If you also installed Boxes through
Flatpak, test the native `gnome-boxes` executable before changing Flatpak access.

## Config sync between machines (`dots`)

App folders listed in `my.features.dots.apps` live in `config/<app>` and are
symlinked into `~/.config`. Editing a file edits the repository working tree.

```bash
dots status     # links, pending changes, auto-sync state
dots on         # commit, rebase and push automatically every 5 min
dots off        # stop; nothing happens in the background
dots sync       # one round now
dots adopt      # move existing ~/.config folders into the repository
```

A conflict aborts the rebase, switches auto-sync off and sends a notification.
Files over 5 MB are never committed.

## Agent VM (`agentbox`)

A headless NixOS microVM with Claude Code and Codex. It sees one host folder
(`my.features.agentbox.workspace`, mounted at `/work`) and nothing else. The
host firewall lets it reach the internet but not your LAN or host services.

```nix
my.features.agentbox.enable = true;
my.features.agentbox.sshKeys = [ "ssh-ed25519 AAAA... you@host" ];
```

```bash
agentbox start      # boot the VM
agentbox code       # VSCodium connected to /work (installs Open Remote - SSH)
agentbox ssh        # shell; there: yolo-claude, yolo-codex
agentbox reset --yes
```

Log in to your agent accounts and to GitHub inside the VM (`gh auth login`,
preferably with a token limited to the repositories the agents may touch).

## Boot splash

```bash
sudo plmf theme list
sudo plmf theme set zoot      # Arknights-style terminal animation, applies on next boot
sudo plmf theme reset
```

Themes are bundled at build time (`pkgs/plymouth-themes`); the choice is a small
file on the EFI partition, so switching needs no rebuild. The LUKS prompt stays
on the console.

## Local AI and dev shells

```bash
ai on | off | ui | status       # Ollama (+ Open WebUI), never started at boot
nix develop .#ai-rocm           # llama.cpp + uv + huggingface-cli (ai-cpu, ai-cuda)
echo "use flake ~/nix-config#ai-cuda" > .envrc && direnv allow
```

## Maintenance (`nx`)

```bash
nx status           # instant overview
nx check            # which inputs have updates (~2 s, no downloads)
nx update           # refresh all inputs, build, diff, confirm, switch
nx update profiles  # only user-profile packages, without a system rebuild
nx debug            # detailed local diagnostics, findings and bounded logs
nx switch           # rebuild this host after editing the config
nx pull             # fetch the repo, fast-forward only
nx gen | nx clean | nx rollback | nx optimise
```

See [UPDATES.md](UPDATES.md). Anything can be run with `--json` for tools.

User-profile packages have their own CLI, independent of system feature selection:

```bash
nx profiles                       # list installed profile packages
nx profiles install nixpkgs#hello
nx profiles remove hello
nx profiles update                # all packages; optionally append exact names
nx profiles history
nx profiles rollback              # restore the previous user-profile generation
```

Use `--profile PATH` for another profile and `--yes` for confirmed mutations in
scripts. These commands do not rebuild NixOS. Gaming and desktop choices stay in
`nixctl`.

For installation, update or desktop failures, use `nx debug`, or select sections
with `nx debug nix cache repo`. `nx debug --full --json --output ~/nx-debug.json`
saves a detailed report. Unit journals, previous boots and failing store paths
can be inspected separately. See [diagnostics and report options](UPDATES.md#diagnostics-and-support-reports).

## Optional local coding AI

`my.features.local-ai.enable` adds on-demand rootless Strata HIP and an offline
workspace coding container. It is disabled on both hosts and includes no models
or automatic model downloads. See [setup, isolation and model-free tests](docs/LOCAL-AI.md).

## Layout

```text
flake.nix            inputs, hosts, packages, dev shells
modules/core/        always-on modules
modules/desktop/     compositors, shells, greeter, GPU
modules/features/    optional features (my.features.*)
hosts/<host>/        hardware facts + feature switches
pkgs/                nx, dots, nixctl, agentbox, plmf, themes
config/<app>/        synchronised app configuration
tests/               shell and VM tests (run in CI)
```

Host-specific hardware data, credentials and private user data must never be
committed. `ci-<host>` configurations exist only so CI can evaluate without
real hardware.
