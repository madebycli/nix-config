{ ... }:

{
  programs.niri.enable = true;

  # Niri defines its own portal default in current NixOS. Do not add a second
  # xdg.portal.config.niri.default here.
}
