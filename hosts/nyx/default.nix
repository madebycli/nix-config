{ config, lib, modulesPath, pkgs, ... }:

let
  generatedHardware = import ./hardware-configuration.nix {
    inherit config lib modulesPath pkgs;
  };

  generatedLuksDevices = generatedHardware.boot.initrd.luks.devices or { };
in
{
  imports = [
    ./hardware-configuration.nix
    ../../modules/nixos/graphics-amd.nix
  ];

  networking.hostName = "nyx";

  boot = {
    kernelPackages = pkgs.cachyosKernels.linuxPackages-cachyos-bore-zen4;
    # kernelPackages = pkgs.linuxPackages_latest;

    initrd.luks.devices = lib.mapAttrs (_name: _device: {
      bypassWorkqueues = true;
      allowDiscards = true;
    }) generatedLuksDevices;
  };

  services.udev.extraRules = ''
    ACTION=="add|change", SUBSYSTEM=="block", KERNEL=="nvme[0-9]n[0-9]", ATTR{queue/scheduler}="mq-deadline"
  '';

  hardware.cpu.amd.updateMicrocode = true;

  systemd.services.nyx-initial-fstrim = {
    description = "Run one initial TRIM after activating the Nyx configuration";
    wantedBy = [ "multi-user.target" ];
    after = [ "local-fs.target" ];
    wants = [ "local-fs.target" ];

    unitConfig.ConditionPathExists = "!/var/lib/nixos-config/nyx-initial-fstrim.done";

    serviceConfig = {
      Type = "oneshot";
      StateDirectory = "nixos-config";
      ExecStartPre = "${pkgs.coreutils}/bin/sleep 10";
      ExecStart = "${pkgs.util-linux}/bin/fstrim -v /";
      ExecStartPost = "${pkgs.coreutils}/bin/touch /var/lib/nixos-config/nyx-initial-fstrim.done";
    };
  };
}
