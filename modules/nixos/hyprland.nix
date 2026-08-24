{ inputs, shell, ... }:

{
  imports = [
    inputs.hyprland.nixosModules.default
  ];

  programs.hyprland.enable = true;
  programs.noctalia.systemd.enable = shell == "noctalia";
}
