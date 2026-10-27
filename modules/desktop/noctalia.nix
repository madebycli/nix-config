{ config, lib, pkgs, ... }:

{
  # Keep the existing nixpkgs NixOS module and all desktop-shell switches.
  config.programs.noctalia = lib.mkIf (config.my.desktop.shell == "noctalia") {
    enable = true;
    # Former source: inputs.noctalia.packages.${pkgs.stdenv.hostPlatform.system}.default;
    package = pkgs.noctalia; # nixos-unstable via the root nixpkgs input
    recommendedServices.enable = false;
    systemd.enable = false;
  };
}
