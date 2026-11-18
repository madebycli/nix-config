{ config, inputs, lib, pkgs, ... }:

let
  enabled = lib.elem "mango" config.my.desktop.compositors;
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
    # the dmenu chooser, with a store path because the user service PATH need
    # not include system-profile programs.
    xdg.portal.wlr = {
      enable = true;
      settings.screencast = {
        chooser_type = "dmenu";
        chooser_cmd = "${pkgs.fuzzel}/bin/fuzzel --dmenu --prompt='Share screen: '";
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
