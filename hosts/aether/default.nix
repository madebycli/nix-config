{ pkgs, ... }:

{
  imports = [
    ./hardware-configuration.nix
    ../../modules/nixos/graphics-nvidia.nix
  ];

  networking.hostName = "aether";

  # Aether has the concrete ESP/root layout required by the PLMF selector;
  # Nyx intentionally uses a hardware-configuration placeholder.
  plmf.bootSplash.enable = true;

  boot.kernelPackages =
    pkgs.cachyosKernels.linuxPackages-cachyos-bore-x86_64-v3;

  services.udev.extraRules = ''
    ACTION=="add|change", SUBSYSTEM=="block", KERNEL=="nvme[0-9]n[0-9]", ATTR{queue/scheduler}="mq-deadline"
  '';

  hardware.cpu.intel.updateMicrocode = true;
  services.thermald.enable = true;
}
