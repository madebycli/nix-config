{ config, lib, ... }:

{
  # Module and package come from nixpkgs (unstable); no separate Flake input.
  config.programs.noctalia = lib.mkIf (config.my.desktop.shell == "noctalia") {
    enable = true;
    recommendedServices.enable = false;
    systemd.enable = false;
  };
}
