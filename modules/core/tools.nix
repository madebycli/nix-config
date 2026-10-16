{ lib, pkgs, ... }:

let
  tools = import ../../pkgs/tools.nix { inherit pkgs; };
  # The installer is only meant to be run via `nix run .#install`.
  installed = lib.filterAttrs (name: _: name != "nixos-config-install") tools;
in
{
  environment.systemPackages = lib.attrValues installed;
}
