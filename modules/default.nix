{ inputs, ... }:

{
  imports = [
    inputs.home-manager.nixosModules.home-manager

    ./options.nix
    ./core/base.nix
    ./core/storage-tuning.nix
    ./core/home.nix
    ./core/tools.nix
    ./desktop
    ./features
  ];

  nixpkgs.overlays = [ inputs.nix-cachyos-kernel.overlays.pinned ];
}
