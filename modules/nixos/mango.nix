{ inputs, pkgs, ... }:

{
  # Neuere Nixpkgs-Versionen enthalten selbst ein programs.mango-Modul.
  # Wir deaktivieren nur dieses eingebaute Modul und verwenden weiterhin das
  # separat gepinnte Mango-Flake-Modul. Dadurch aktualisiert `system-update
  # base` nicht versehentlich die Mango-Quellversion und die Option
  # programs.mango.enable wird nicht doppelt deklariert.
  disabledModules = [
    "programs/wayland/mango.nix"
  ];

  imports = [
    inputs.mango.nixosModules.mango
  ];

  programs.mango = {
    enable = true;
    addLoginEntry = true;
  };

  # The NixOS-only Mango module installs the compositor session but does not
  # provide the user target that activates graphical-session.target. Portal
  # services use that target as their session lifetime boundary.
  systemd.user.targets.mango-session = {
    description = "MangoWM graphical session";
    unitConfig = {
      Documentation = [ "man:systemd.special(7)" ];
      BindsTo = [ "graphical-session.target" ];
      Wants = [ "graphical-session-pre.target" ];
      After = [ "graphical-session-pre.target" ];
    };
  };

  # Keep screen capture on wlroots while using GNOME's GTK4 chooser only for
  # the FileChooser interface.
  xdg.portal.config.mango = {
    default = [ "gtk" ];
    "org.freedesktop.impl.portal.FileChooser" = [ "gnome" ];
    "org.freedesktop.impl.portal.ScreenCast" = [ "wlr" ];
    "org.freedesktop.impl.portal.Screenshot" = [ "wlr" ];
    "org.freedesktop.impl.portal.Inhibit" = [ ];
  };

  # Workaround dependencies for Mango/wlroots clipboard interoperability
  # with Steam Proton XWayland clients.
  environment.systemPackages = with pkgs; [
    wl-clipboard
    xclip
  ];
}
