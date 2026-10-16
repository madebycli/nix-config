{ config, lib, ... }:

{
  programs.hyprland.enable = lib.elem "hyprland" config.my.desktop.compositors;
}
