{ pkgs, ... }:

{
  imports = [
    ./hardware-configuration.nix
    ../../modules/nixos/graphics-nvidia.nix
  ];

  networking.hostName = "aether";

  boot.kernelPackages =
    pkgs.cachyosKernels.linuxPackages-cachyos-bore-x86_64-v3;

services.udev.extraRules = ''
  ACTION=="add|change", SUBSYSTEM=="block", KERNEL=="nvme[0-9]n[0-9]", ATTR{queue/scheduler}="mq-deadline"
'';



#boot.initrd.luks.devices."luks-REDACTED-AETHER" = {
#  bypassWorkqueues = true;
#  allowDiscards = true;
#};

  hardware.cpu.intel.updateMicrocode = true;
  services.thermald.enable = true;
}
