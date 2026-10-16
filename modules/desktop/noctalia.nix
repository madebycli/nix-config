{ config, inputs, lib, ... }:

{
  # Neuere Nixpkgs-Versionen enthalten selbst ein programs.noctalia-Modul.
  # Nur dieses eingebaute Modul wird deaktiviert; das gepinnte Flake-Modul
  # bleibt massgeblich.
  disabledModules = [
    "programs/wayland/noctalia.nix"
  ];

  imports = [
    inputs.noctalia.nixosModules.default
  ];

  config.programs.noctalia = lib.mkIf (config.my.desktop.shell == "noctalia") {
    enable = true;
    recommendedServices.enable = false;
    systemd.enable = false;
  };
}
