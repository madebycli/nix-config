{ config, lib, ... }:

{
  # Niri defines its own portal default in current NixOS. Do not add a second
  # xdg.portal.config.niri.default here.
  programs.niri.enable = lib.elem "niri" config.my.desktop.compositors;
}
