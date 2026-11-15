# Check real session routing: file dialogs must not hijack capture backends.
let
  flake = builtins.getFlake (toString ../.);
  lib = flake.inputs.nixpkgs.lib;
  base = host: flake.nixosConfigurations."ci-${host}";
  desktop = names: (base "nyx").extendModules {
    modules = [{
      my.desktop.compositors = lib.mkForce names;
      my.desktop.defaultSession = lib.mkForce (builtins.head names);
      my.desktop.shell = lib.mkForce "noctalia";
    }];
  };
  includes = package: packages:
    builtins.any (p: p.drvPath == package.drvPath) packages;
  route = config: name: interface:
    let section = config.xdg.portal.config.${name};
    in section."org.freedesktop.impl.portal.${interface}"
       or (builtins.head (lib.splitString ";" section.default));
  common = system:
    let c = system.config; pkgs = system.pkgs; in
    includes pkgs.xdg-desktop-portal-gnome c.xdg.portal.extraPortals
    && includes pkgs.xdg-desktop-portal-gtk c.xdg.portal.extraPortals
    && includes pkgs.nautilus c.services.dbus.packages
    && includes pkgs.nautilus c.environment.systemPackages
    && c.xdg.portal.config.common."org.freedesktop.impl.portal.FileChooser" == "gnome"
    && !(c.environment.sessionVariables ? GTK_USE_PORTAL)
    && c.services.pipewire.enable;
  mango = system:
    let
      c = system.config;
      chooser = c.xdg.portal.wlr.settings.screencast;
    in
    common system
    && c.xdg.portal.wlr.enable
    && c.systemd.user.services.xdg-desktop-portal-gnome.overrideStrategy == "asDropin"
    && c.systemd.user.services.xdg-desktop-portal-gnome.unitConfig.Requisite == ""
    && chooser.chooser_type == "dmenu"
    && chooser.chooser_cmd == "${system.pkgs.fuzzel}/bin/fuzzel --dmenu --prompt='Share screen: '"
    && !(chooser ? output_name)
    && route c "mango" "ScreenCast" == "wlr"
    && route c "mango" "Screenshot" == "wlr"
    && route c "mango" "FileChooser" == "gnome";
  nativeCapture = name: backend: system:
    let c = system.config; in
    common system
    && route c name "FileChooser" == "gnome"
    && route c name "ScreenCast" == backend
    && route c name "Screenshot" == backend;
  mixed = desktop [ "mango" "niri" "hyprland" ];
in
{
  nyxMangoHasAbsoluteChooserAndGnomeFiles = mango (base "nyx");
  aetherMangoHasAbsoluteChooserAndGnomeFiles = mango (base "aether");
  niriKeepsNativeCaptureAndGnomeFiles = nativeCapture "niri" "gnome" (desktop [ "niri" ]);
  hyprlandKeepsNativeCaptureAndGnomeFiles = nativeCapture "hyprland" "hyprland" (desktop [ "hyprland" ]);
  mixedSessionsKeepIndependentCapture = mango mixed
    && nativeCapture "niri" "gnome" mixed
    && nativeCapture "hyprland" "hyprland" mixed;
}
