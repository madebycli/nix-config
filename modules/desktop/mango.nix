{ config, inputs, lib, pkgs, ... }:

let
  enabled = lib.elem "mango" config.my.desktop.compositors;
in
{
  # Neuere Nixpkgs-Versionen enthalten selbst ein programs.mango-Modul.
  # Wir deaktivieren nur dieses eingebaute Modul und verwenden weiterhin das
  # separat gepinnte Mango-Flake-Modul.
  disabledModules = [
    "programs/wayland/mango.nix"
  ];

  imports = [
    inputs.mango.nixosModules.mango
  ];

  config = lib.mkIf enabled {
    programs.mango = {
      enable = true;
      addLoginEntry = true;
    };

    # Workaround dependencies for Mango/wlroots clipboard interoperability
    # with Steam Proton XWayland clients.
    environment.systemPackages = with pkgs; [
      wl-clipboard
      xclip
    ];
  };
}
