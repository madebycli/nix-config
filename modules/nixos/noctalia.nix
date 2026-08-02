{ inputs, ... }:

{
  # Neuere Nixpkgs-Versionen enthalten selbst ein programs.noctalia-Modul.
  # Wir deaktivieren ausschließlich dieses eingebaute Modul und verwenden
  # weiterhin das separat gepinnte Noctalia-Flake-Modul. Dadurch bleibt
  # `system-update base` unabhängig von der Noctalia-Quellversion und es gibt
  # keine doppelte Deklaration von programs.noctalia.enable.
  disabledModules = [
    "programs/wayland/noctalia.nix"
  ];

  imports = [
    inputs.noctalia.nixosModules.default
  ];

  programs.noctalia = {
    enable = true;
    recommendedServices.enable = false;
    systemd.enable = false;
  };
}
