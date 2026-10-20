{ config, lib, pkgs, ... }:

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
      faugus-launcher
      prismlauncher
      winetricks
      wineWow64Packages.waylandFull
    ];
  };
}
