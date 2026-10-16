{ config, inputs, lib, pkgs, ... }:

{
  config = lib.mkIf (config.my.desktop.shell == "caelestia") {
    home-manager.users.${config.my.user} = {
      imports = [
        inputs.caelestia-shell.homeManagerModules.default
      ];

      programs.caelestia = {
        enable = true;
        package = inputs.caelestia-shell.packages.${pkgs.stdenv.hostPlatform.system}.with-cli;
        systemd.enable = true;
      };
    };
  };
}
