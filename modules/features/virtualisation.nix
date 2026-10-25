{ config, lib, pkgs, ... }:

let
  cfg = config.my.features.virtualisation;
in
{
  options.my.features.virtualisation = {
    enable = lib.mkEnableOption "GNOME Boxes with QEMU/KVM and libvirt";
    cpuVendor = lib.mkOption {
      type = lib.types.enum [ "amd" "intel" ];
      description = "Host CPU vendor, used to load the matching KVM module. Set with the host hardware facts.";
    };
  };

  config = lib.mkIf cfg.enable {
    boot.kernelModules = [ "kvm" "kvm-${cfg.cpuVendor}" ];

    virtualisation.libvirtd = {
      enable = true;
      qemu = {
        package = pkgs.qemu_kvm;
        runAsRoot = false;
        swtpm.enable = true;
      };
    };

    users.users.${config.my.user}.extraGroups = [ "kvm" "libvirtd" ];
    users.users.qemu-libvirtd.extraGroups = [ "kvm" ];
    environment.systemPackages = [ pkgs.gnome-boxes ];
  };
}
