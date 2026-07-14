{ pkgs, ... }:

{
  imports = [
    ./hardware-configuration.nix
    ../../modules/nixos/graphics-nvidia.nix
  ];

  networking.hostName = "aether";

  boot.kernelPackages =
    pkgs.cachyosKernels.linuxPackages-cachyos-bore-x86_64-v3;

  hardware.cpu.intel.updateMicrocode = true;
  services.thermald.enable = true;
}
