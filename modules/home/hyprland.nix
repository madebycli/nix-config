{ inputs, pkgs, ... }:

{
  imports = [
    inputs.hyprland.homeManagerModules.default
  ];

  wayland.windowManager.hyprland = {
    enable = true;
    package = inputs.hyprland.packages.${pkgs.stdenv.hostPlatform.system}.hyprland;
    systemd.enable = true;

    settings = {
      "$mod" = "SUPER";

      monitor = [
        ",preferred,auto,1"
      ];

      input = {
        kb_layout = "de";
        follow_mouse = 1;
      };

      bind = [
        "$mod, Return, exec, ghostty"
        "$mod, D, exec, fuzzel"
        "$mod SHIFT, Q, killactive"
        "$mod SHIFT, E, exit"
        "$mod, F, fullscreen"
      ];
    };
  };
}
