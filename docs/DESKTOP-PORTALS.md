# Desktop portals

The desktop configuration uses GNOME's GTK4/Nautilus file chooser for applications
that request a file dialog through the desktop portal. This includes native
portal-capable Chromium browsers such as Helium and Firefox browsers such as
LibreWolf. Nautilus is installed and registered for D-Bus activation. Flatpak
permissions and application settings are not changed.

Screen sharing stays with the compositor's own backend:

| Session | ScreenCast / Screenshot | FileChooser |
|---|---|---|
| Mango | wlr | GNOME / Nautilus |
| Niri | GNOME | GNOME / Nautilus |
| Hyprland | Hyprland | GNOME / Nautilus |

Mango's wlr portal uses its supported `dmenu` chooser with an absolute Nix store
path to Fuzzel. The service does not need the interactive shell's PATH. This fixes
the selection failure where Vesktop reports `ScreenCastPortal failed: 3` and the
portal journal lists missing `wmenu`, `wofi`, `rofi`, `bemenu`, `mew` and `fuzzel`,
followed by `no output found`. A working GPU Screen Recorder does not establish
that this portal selection path works.

GNOME's backend normally requires an active `graphical-session.target`. Mango's
native session exports its D-Bus activation environment but does not start this
target. A declarative systemd drop-in clears only the GNOME backend's `Requisite`
in configurations with Mango installed, allowing D-Bus activation. The upstream
ordering and stop binding remain. No session wrapper or startup script is added.

## Apply

From any directory, using the checkout configured in `/etc/nixctl.conf`:

```sh
nx pull && nx switch
```

Log out and back in, then reopen Vesktop and the browsers. Test a screen share
and an upload/download file dialog. Config evaluation and CI do not replace this
test in an actual Wayland session.

An application that uses its own GTK3 dialog instead of the FileChooser portal
keeps that dialog. This configuration does not globally force `GTK_USE_PORTAL`
or install per-application wrappers. Existing user portal configurations under
`~/.config/xdg-desktop-portal/` take precedence over the system configuration;
check those if the selected backend differs.

For diagnostics after a failed share:

```sh
journalctl --user -b -u xdg-desktop-portal -u xdg-desktop-portal-wlr --no-pager -n 100
```

The routing and service configuration are checked by `tests/portals.nix` for
both hosts, each compositor separately and a mixed installation. The pinned
[wlr configuration manual](https://github.com/emersion/xdg-desktop-portal-wlr/blob/v0.8.4/xdg-desktop-portal-wlr.5.scd)
documents the chooser options; the
[GNOME backend](https://gitlab.gnome.org/GNOME/xdg-desktop-portal-gnome)
provides the FileChooser interface through Nautilus.
