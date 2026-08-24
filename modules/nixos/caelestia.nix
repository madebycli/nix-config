{ inputs, pkgs, ... }:

{
  home-manager.users.xxxxx = {
    imports = [
      inputs.caelestia-shell.homeManagerModules.default
    ];

    programs.caelestia = {
      enable = true;
      package = inputs.caelestia-shell.packages.${pkgs.stdenv.hostPlatform.system}.with-cli;
      systemd.enable = true;
    };
  };
}
