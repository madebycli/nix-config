{ pkgs, ... }:

{
  imports = [
    ./helium.nix
  ];

  home = {
    username = "xxxxx";
    homeDirectory = "/home/xxxxx";
    stateVersion = "25.11";

    pointerCursor = {
      enable = true;
      name = "Bibata-Modern-Classic";
      package = pkgs.bibata-cursors;
      size = 22;
      gtk.enable = true;
      x11.enable = true;
    };
  };
}
