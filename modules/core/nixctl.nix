{ config, lib, pkgs, ... }:

let
  nx = pkgs.callPackage ../../pkgs/nx { };
  nixctl = pkgs.callPackage ../../pkgs/nixctl { };
  dots = pkgs.callPackage ../../pkgs/dots { };
  settings = pkgs.callPackage ../../pkgs/nix-settings { inherit nx nixctl dots; };
in
{
  environment.systemPackages = [ nixctl settings ];

  environment.etc."nixctl.conf".text = ''
    REPO=${lib.escapeShellArg config.my.repoPath}
    HOST=${lib.escapeShellArg config.networking.hostName}
  '';
}
