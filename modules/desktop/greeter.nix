{ config, inputs, pkgs, ... }:

{
  imports = [
    inputs.noctalia-greeter.nixosModules.default
  ];

  programs.noctalia-greeter = {
    enable = true;
    greeter-args = "--session ${config.my.desktop.defaultSession}";

    settings = {
      keyboard.layout = "de";

      cursor = {
        theme = "Bibata-Modern-Classic";
        size = 22;
        path = "${pkgs.bibata-cursors}/share/icons";
      };

      user.default = config.my.user;
    };
  };
}
