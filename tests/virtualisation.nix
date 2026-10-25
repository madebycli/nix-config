# Evaluate real NixOS configurations. No VM, device, build or activation needed.
let
  flake = builtins.getFlake (toString ../.);
  lib = flake.inputs.nixpkgs.lib;
  cfg = name: flake.nixosConfigurations.${name}.config;
  hasBoxes = c: builtins.elem "gnome-boxes" (map lib.getName c.environment.systemPackages);
  groups = c: c.users.users.${c.my.user}.extraGroups;
  enabled = host: vendor:
    let c = cfg "ci-${host}-full"; in
    c.my.features.virtualisation.enable
    && hasBoxes c
    && c.virtualisation.libvirtd.enable
    && !c.virtualisation.libvirtd.qemu.runAsRoot
    && c.virtualisation.libvirtd.qemu.swtpm.enable
    && c.virtualisation.libvirtd.qemu.package.drvPath == flake.nixosConfigurations."ci-${host}-full".pkgs.qemu_kvm.drvPath
    && builtins.elem "kvm" (groups c)
    && builtins.elem "libvirtd" (groups c)
    && builtins.elem "kvm" c.users.users.qemu-libvirtd.extraGroups
    && builtins.elem "kvm-${vendor}" c.boot.kernelModules
    && !(builtins.elem "kvm-${if vendor == "amd" then "intel" else "amd"}" c.boot.kernelModules);
  disabled = host:
    let
      c = (flake.nixosConfigurations."ci-${host}".extendModules {
        modules = [{ my.features.virtualisation.enable = lib.mkForce false; }];
      }).config;
    in
    !hasBoxes c
    && !c.virtualisation.libvirtd.enable
    && !(builtins.elem "libvirtd" (groups c))
    && !(builtins.elem "kvm-amd" c.boot.kernelModules)
    && !(builtins.elem "kvm-intel" c.boot.kernelModules)
    && c.my.features.gaming.enable
    && !c.my.features.agentbox.enable
    && !c.my.features.local-ai.enable;
in
{
  nyxDefaultEnabled = (cfg "ci-nyx").my.features.virtualisation.enable;
  aetherDefaultDisabled = !(cfg "ci-aether").my.features.virtualisation.enable;
  nyxEnabledBackend = enabled "nyx" "amd";
  aetherEnabledBackend = enabled "aether" "intel";
  nyxDisableRemovesFeature = disabled "nyx";
  aetherDisableRemovesFeature = disabled "aether";
}
