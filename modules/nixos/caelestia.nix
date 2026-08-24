{ inputs, ... }:

{
  home-manager.users.xxxxx = {
    imports = [
      inputs.caelestia-shell.homeManagerModules.default
    ];

    programs.caelestia = {
      enable = true;
      systemd.enable = true;
    };
  };
}
