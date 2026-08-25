{ ... }:

{
  wayland.windowManager.hyprland = {
    enable = true;
    package = null;
    portalPackage = null;
    configType = "hyprlang";
    systemd.enable = true;

    settings = {
      "$mod" = "SUPER";
      monitor = [ ",preferred,auto,1" ];
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
