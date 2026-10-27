{ config, lib, pkgs, ... }:

let
  colorCommand = pkgs.writeShellApplication {
    name = "helium-noctalia-color";
    text = ''
      exec ${pkgs.python3}/bin/python3 ${../../config/noctalia-helium/helium-noctalia-color} "$@"
    '';
  };
in

{
  # Keep the existing nixpkgs NixOS module and all desktop-shell switches.
  config.programs.noctalia = lib.mkIf (config.my.desktop.shell == "noctalia") {
    enable = true;
    # Former source: inputs.noctalia.packages.${pkgs.stdenv.hostPlatform.system}.default;
    package = pkgs.noctalia; # nixos-unstable via the root nixpkgs input
    recommendedServices.enable = false;
    systemd.enable = false;
  };

  config.home-manager.users.${config.my.user} = lib.mkIf (config.my.desktop.shell == "noctalia") {
    home.packages = [ pkgs.bubblewrap colorCommand ];

    home.file.".local/share/noctalia/plugins/helium-theme" = {
      source = ../../config/noctalia-helium;
      force = true;
    };

    # Seed a fresh profile only. Afterwards Noctalia owns this mutable file.
    home.activation.noctaliaHeliumDefaults = {
      after = [ "writeBoundary" ];
      before = [ ];
      data = ''
        settings="$HOME/.local/state/noctalia/settings.toml"
        if [ ! -e "$settings" ]; then
          run mkdir -p "$HOME/.local/state/noctalia"
          run install -m 600 ${../../config/noctalia-helium/initial-settings.toml} "$settings"
        fi
      '';
    };
  };
}
