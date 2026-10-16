# Maintenance commands shipped with this configuration (see scripts/).
{ pkgs }:

let
  mkTool = { name, script, runtimeInputs }:
    pkgs.writeShellApplication {
      inherit name runtimeInputs;
      inheritPath = true;
      text = builtins.readFile script;
      checkPhase = ''
        ${pkgs.bash}/bin/bash -n "$target"
      '';
    };

  tools = with pkgs; {
    config-update = { script = ../scripts/update.sh; runtimeInputs = [ coreutils findutils git jq nix ]; };
    nix-help = { script = ../scripts/nix-help.sh; runtimeInputs = [ coreutils ]; };
    nix-status = { script = ../scripts/nix-status.sh; runtimeInputs = [ coreutils findutils gawk git jq nix ]; };
    nix-updates = { script = ../scripts/nix-updates.sh; runtimeInputs = [ coreutils findutils git jq nix ]; };
    nix-refresh = { script = ../scripts/nix-refresh.sh; runtimeInputs = [ coreutils findutils gh git jq nix ]; };
    nix-generations = { script = ../scripts/nix-generations.sh; runtimeInputs = [ coreutils findutils gawk nix ]; };
    nix-clean = { script = ../scripts/nix-clean.sh; runtimeInputs = [ coreutils findutils nix ]; };
    nix-optimize = { script = ../scripts/nix-optimize.sh; runtimeInputs = [ coreutils gawk nix ]; };
    nix-rollback = { script = ../scripts/nix-rollback.sh; runtimeInputs = [ coreutils nix ]; };
    nixos-config-install = { script = ../scripts/install.sh; runtimeInputs = [ coreutils findutils git gnugrep gnused nix rsync ]; };
  };
in
builtins.mapAttrs (name: spec: mkTool (spec // { inherit name; })) tools
