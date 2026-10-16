# The installer, run once via `nix run .#install`. Day-to-day commands live in pkgs/nx.
{ pkgs }:

{
  nixos-config-install = pkgs.writeShellApplication {
    name = "nixos-config-install";
    inheritPath = true;
    runtimeInputs = with pkgs; [ coreutils findutils git gnugrep gnused nix ];
    text = builtins.readFile ../scripts/install.sh;
    checkPhase = ''
      ${pkgs.bash}/bin/bash -n "$target"
    '';
  };
}
