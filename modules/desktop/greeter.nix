{ config, pkgs, ... }:

{
  # Module and package come from nixpkgs (unstable); no separate Flake input.
  services.displayManager.noctalia-greeter = {
    enable = true;
    extraArgs = [ "--session" config.my.desktop.defaultSession ];

    cursorTheme = {
      package = pkgs.bibata-cursors;
      name = "Bibata-Modern-Classic";
    };

    settings = {
      keyboard.layout = "de";
      cursor.size = 22;
      user.default = config.my.user;
    };
  };
}
