{ config, pkgs, ... }:

{
  imports = [
    ./hardware-configuration.nix
    ./features.nix
    ../../modules/desktop/graphics-amd.nix
  ];

  my.hardwareConfig = ./hardware-configuration.nix;

  networking.hostName = "nyx";

  boot.kernelPackages =
    if config.my.kernel == "cachyos" then
      pkgs.cachyosKernels.linuxPackages-cachyos-bore-zen4
    else
      pkgs.linuxPackages_latest;

  services.udev.extraRules = ''
    ACTION=="add|change", SUBSYSTEM=="block", KERNEL=="nvme[0-9]n[0-9]", ATTR{queue/scheduler}="mq-deadline"
  '';

  hardware.cpu.amd.updateMicrocode = true;

  my.features.ai.acceleration = "rocm";
}
