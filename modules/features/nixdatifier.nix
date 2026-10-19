{ config, lib, inputs, ... }:

{
  imports = [ inputs.nixdatifier-noctalia.nixosModules.default ];
  options.my.features.nixdatifier.enable = lib.mkEnableOption "the native Noctalia Nix panel";

  config = lib.mkIf (config.my.features.nixdatifier.enable && config.my.desktop.shell == "noctalia") {
    programs.nixdatifier-noctalia.enable = true;
    home-manager.sharedModules = [
      inputs.nixdatifier-noctalia.homeManagerModules.default
      { programs.nixdatifier-noctalia.enable = true; }
    ];
  };
}
