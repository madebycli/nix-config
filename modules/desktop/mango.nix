{ config, inputs, lib, pkgs, ... }:

let
  enabled = lib.elem "mango" config.my.desktop.compositors;

  # Vesktop asks the portal a second time right after a source was picked.
  # Without this, a second fuzzel menu stays open during the stream, and
  # closing it with Escape cancels that request and ends the stream. A repeat
  # request within 30 seconds gets the previous choice back if it is still
  # offered; otherwise fuzzel opens as usual. A cancelled menu is not stored.
  screencastChooser = pkgs.writeShellScript "mango-screencast-chooser" ''
    PATH=${lib.makeBinPath [ pkgs.coreutils pkgs.gnugrep pkgs.fuzzel ]}
    cache="''${XDG_RUNTIME_DIR:-/tmp}/mango-screencast-choice"
    options=$(cat)

    if [ -f "$cache" ]; then
      age=$(( $(date +%s) - $(stat -c %Y "$cache") ))
      last=$(cat "$cache")
      if [ "$age" -lt 30 ] && [ -n "$last" ] \
        && printf '%s\n' "$options" | grep -qxF -- "$last"; then
        printf '%s\n' "$last"
        exit 0
      fi
    fi

    choice=$(printf '%s\n' "$options" | fuzzel --dmenu --prompt='Share screen: ') || exit 1
    [ -n "$choice" ] || exit 1
    printf '%s\n' "$choice" > "$cache"
    printf '%s\n' "$choice"
  '';
in
{
  # Neuere Nixpkgs-Versionen enthalten selbst ein programs.mango-Modul.
  # Wir deaktivieren nur dieses eingebaute Modul und verwenden weiterhin das
  # separat gepinnte Mango-Flake-Modul.
  disabledModules = [
    "programs/wayland/mango.nix"
  ];

  imports = [
    inputs.mango.nixosModules.mango
  ];

  config = lib.mkIf enabled {
    programs.mango = {
      enable = true;
      addLoginEntry = true;
    };

    # Screen sharing on mango uses the official NixOS wlr portal module. The
    # GNOME backend has no ScreenCast interface outside GNOME Shell. Fuzzel is
    # the dmenu chooser, called through screencastChooser above.
    xdg.portal.wlr = {
      enable = true;
      settings.screencast = {
        chooser_type = "dmenu";
        chooser_cmd = "${screencastChooser}";
      };
    };

    # Mango has its own portal section. The mango flake module also sets keys
    # there, so this whole section is forced to avoid conflicting definitions.
    xdg.portal.config.mango = lib.mkForce {
      default = [ "gnome" ];
      "org.freedesktop.impl.portal.FileChooser" = [ "gnome" ];
      "org.freedesktop.impl.portal.ScreenCast" = [ "wlr" ];
      "org.freedesktop.impl.portal.Screenshot" = [ "wlr" ];
      "org.freedesktop.impl.portal.Inhibit" = [ "none" ];
    };

    # Mango exports its activation environment itself, but its native session
    # does not start graphical-session.target. Allow the file chooser backend
    # to be D-Bus activated there; retain its upstream ordering and stop binding.
    systemd.user.services.xdg-desktop-portal-gnome = {
      overrideStrategy = "asDropin";
      unitConfig.Requisite = "";
    };

    # Workaround dependencies for Mango/wlroots clipboard interoperability
    # with Steam Proton XWayland clients.
    environment.systemPackages = with pkgs; [
      wl-clipboard
      xclip
    ];
  };
}
