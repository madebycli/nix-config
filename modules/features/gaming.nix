{ config, lib, pkgs, ... }:

let
  # Nixpkgs hard-wires LSFG paths into Faugus, with no feature flag.
  # An empty provider keeps its optional library detection working without
  # pulling lsfg-vk into the system. Existing user-installed libraries are
  # outside this module's scope.
  faugusWithoutLsfg = pkgs.faugus-launcher.override {
    lsfg-vk = pkgs.emptyDirectory;
  };
in
{
  options.my.features.gaming.enable = lib.mkEnableOption "Steam, Proton, Wine, launchers and emulators";

  config = lib.mkIf config.my.features.gaming.enable {
    programs = {
      steam = {
        enable = true;
        gamescopeSession.enable = true;
      };

      gamescope = {
        enable = true;
        capSysNice = true;
      };

      gamemode.enable = true;
    };

    environment.systemPackages = with pkgs; [
      eden
      mangohud
      protonup-ng
      protonplus
      umu-launcher
      lutris
      goverlay
      heroic
      faugusWithoutLsfg
      prismlauncher
      winetricks
      wineWow64Packages.waylandFull
    ];
  };
}
