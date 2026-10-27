{ config, pkgs, ... }:

{
  # Keep the nixpkgs module, greetd integration and desktop-session selection.
  services.displayManager.noctalia-greeter = {
    enable = true;
    package = pkgs.noctalia-greeter; # nixos-unstable via the root nixpkgs input
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
