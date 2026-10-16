{ pkgs, ... }:

{
  # `nx` for updates, switching and housekeeping; the installer is run via `nix run`.
  environment.systemPackages = [ (pkgs.callPackage ../../pkgs/nx { }) ];
}
