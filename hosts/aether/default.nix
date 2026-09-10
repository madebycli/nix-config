{ config, lib, pkgs, ... }:

let
  # The generated Aether hardware file uses the conventional
  # /dev/mapper/luks-<UUID> name for the encrypted disk swap, but older
  # generated files do not add the corresponding initrd LUKS entry. Derive it
  # from the local hardware file so no host UUID is committed to the repo.
  encryptedSwapDevices = builtins.filter
    (swap:
      let
        mapperName = lib.strings.removePrefix "/dev/mapper/" swap.device;
        luksUuid = lib.strings.removePrefix "luks-" mapperName;
      in
      lib.hasPrefix "/dev/mapper/luks-" swap.device
      && builtins.match
        "^[0-9A-Fa-f]{8}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{12}$"
        luksUuid != null)
    config.swapDevices;

  encryptedSwapInitrdDevices = lib.listToAttrs (map
    (swap:
      let
        mapperName = lib.strings.removePrefix "/dev/mapper/" swap.device;
        luksUuid = lib.strings.removePrefix "luks-" mapperName;
      in
      {
        name = mapperName;
        value.device = "/dev/disk/by-uuid/${luksUuid}";
      })
    encryptedSwapDevices);
in

{
  imports = [
    ./hardware-configuration.nix
    ../../modules/nixos/graphics-nvidia.nix
  ];

  networking.hostName = "aether";

  # Aether has the concrete ESP/root layout required by the PLMF selector;
  # Nyx intentionally uses a hardware-configuration placeholder.
  plmf.bootSplash.enable = true;

  boot.initrd.luks.devices = encryptedSwapInitrdDevices;

  boot.kernelPackages =
    pkgs.cachyosKernels.linuxPackages-cachyos-bore-x86_64-v3;

  services.udev.extraRules = ''
    ACTION=="add|change", SUBSYSTEM=="block", KERNEL=="nvme[0-9]n[0-9]", ATTR{queue/scheduler}="mq-deadline"
  '';

  hardware.cpu.intel.updateMicrocode = true;
  services.thermald.enable = true;
}
