{ inputs, ... }:

{
  imports = [
    inputs.hyprland.nixosModules.default
  ];

  programs.hyprland = {
    enable = true;
    # The Home Manager module owns the Hyprland package and user configuration.
    package = null;
  };
}
