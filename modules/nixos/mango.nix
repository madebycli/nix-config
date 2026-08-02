{ inputs, ... }:

{
  # Neuere Nixpkgs-Versionen enthalten selbst ein programs.mango-Modul.
  # Wir deaktivieren nur dieses eingebaute Modul und verwenden weiterhin das
  # separat gepinnte Mango-Flake-Modul. Dadurch aktualisiert `system-update
  # base` nicht versehentlich die Mango-Quellversion und die Option
  # programs.mango.enable wird nicht doppelt deklariert.
  disabledModules = [
    "programs/wayland/mango.nix"
  ];

  imports = [
    inputs.mango.nixosModules.mango
  ];

  programs.mango = {
    enable = true;
    addLoginEntry = true;
  };
}
