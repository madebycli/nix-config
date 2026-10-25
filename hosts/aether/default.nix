{ config, pkgs, ... }:

{
  imports = [
    ./hardware-configuration.nix
    ./features.nix
    ../../modules/desktop/graphics-nvidia.nix
  ];

  my.hardwareConfig = ./hardware-configuration.nix;

  # Verify both IDs on the laptop with `lspci -D` before the first switch.
  my.hardware.nvidiaPrime = {
    intelBusId = "PCI:0:2:0";
    nvidiaBusId = "PCI:1:0:0";
  };

  networking.hostName = "aether";

  boot.kernelPackages =
    if config.my.kernel == "cachyos" then
      pkgs.cachyosKernels.linuxPackages-cachyos-bore-x86_64-v3
    else
      pkgs.linuxPackages_latest;

  services.udev.extraRules = ''
    ACTION=="add|change", SUBSYSTEM=="block", KERNEL=="nvme[0-9]n[0-9]", ATTR{queue/scheduler}="mq-deadline"
  '';

  my.features.virtualisation.cpuVendor = "intel";
  hardware.cpu.intel.updateMicrocode = true;
  services.thermald.enable = true;

  my.features.ai.acceleration = "cuda";
}
