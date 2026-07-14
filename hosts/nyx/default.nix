{ pkgs, ... }:

{
  imports = [
    ./hardware-configuration.nix
    ../../modules/nixos/graphics-amd.nix
  ];

  networking.hostName = "nyx";

  boot.kernelPackages = pkgs.cachyosKernels.linuxPackages-cachyos-bore-zen4;
    #boot.kernelPackages = pkgs.linuxPackages_latest;
services.udev.extraRules = ''
  ACTION=="add|change", SUBSYSTEM=="block", KERNEL=="nvme[0-9]n[0-9]", ATTR{queue/scheduler}="mq-deadline"
'';



boot.initrd.luks.devices."luks-REDACTED-NYX" = {
  bypassWorkqueues = true;
  allowDiscards = true;
};
  hardware.cpu.amd.updateMicrocode = true;
}
