{ config, lib, ... }:

{
  programs.hyprland.enable = lib.elem "hyprland" config.my.desktop.compositors;

  # A desktop-specific config supersedes configPackages completely, so retain
  # Hyprland's native capture routes while selecting GNOME for file dialogs.
  xdg.portal.config.hyprland = lib.mkIf config.programs.hyprland.enable {
    default = [ "hyprland" "gtk" ];
    "org.freedesktop.impl.portal.ScreenCast" = [ "hyprland" ];
    "org.freedesktop.impl.portal.Screenshot" = [ "hyprland" ];
    "org.freedesktop.impl.portal.FileChooser" = [ "gnome" ];
    "org.freedesktop.impl.portal.Secret" = [ "gnome-keyring" ];
  };
}
