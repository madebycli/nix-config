{ pkgs, ... }:

{
  xdg.portal = {
    enable = true;
    extraPortals = [
      pkgs.xdg-desktop-portal-gtk
      pkgs.xdg-desktop-portal-gnome
    ];
    config.common = {
      default = [ "gnome" ];
      "org.freedesktop.impl.portal.FileChooser" = [ "gnome" ];
      "org.freedesktop.impl.portal.ScreenCast" = [ "gnome" ];
      "org.freedesktop.impl.portal.Inhibit" = [ "none" ];
    };
  };

  # GNOME's FileChooser delegates to Nautilus via D-Bus. Installing the file
  # manager alone is not sufficient to register its activation service.
  services.dbus.packages = [ pkgs.nautilus ];
}
