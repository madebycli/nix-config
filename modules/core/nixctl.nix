{ config, lib, pkgs, ... }:

{
  environment.systemPackages = [ (pkgs.callPackage ../../pkgs/nixctl { }) ];

  environment.etc."nixctl.conf".text = ''
    REPO=${lib.escapeShellArg config.my.repoPath}
    HOST=${lib.escapeShellArg config.networking.hostName}
  '';
}
