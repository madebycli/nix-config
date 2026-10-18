{ config, lib, pkgs, inputs, ... }:

{
  # Keep the NixOS module from nixpkgs and use the upstream shell package only.
  config.programs.noctalia = lib.mkIf (config.my.desktop.shell == "noctalia") {
    enable = true;
    package = inputs.noctalia.packages.${pkgs.stdenv.hostPlatform.system}.default;
    recommendedServices.enable = false;
    systemd.enable = false;
  };
}
