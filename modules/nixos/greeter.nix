{ defaultSession, inputs, pkgs, ... }:

{
  imports = [
    inputs.noctalia-greeter.nixosModules.default
  ];

  programs.noctalia-greeter = {
    enable = true;
    greeter-args = "--session ${defaultSession}";

    settings = {
      keyboard.layout = "de";

      cursor = {
        theme = "Bibata-Modern-Classic";
        size = 22;
        path = "${pkgs.bibata-cursors}/share/icons";
      };

      user.default = "xxxxx";
    };
  };
}
