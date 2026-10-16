{ lib, ... }:

{
  options.my = {
    user = lib.mkOption {
      type = lib.types.str;
      default = "xxxxx";
      description = "Primary user account of this machine.";
    };

    hardwareConfig = lib.mkOption {
      type = lib.types.path;
      description = ''
        Host hardware-configuration.nix. Read once more by storage-tuning to
        apply LUKS options to every generated device.
      '';
    };
  };
}
