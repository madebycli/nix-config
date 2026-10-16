{ config, lib, ... }:

{
  options.my = {
    user = lib.mkOption {
      type = lib.types.str;
      default = "xxxxx";
      description = "Primary user account of this machine.";
    };

    repoPath = lib.mkOption {
      type = lib.types.str;
      default = "/home/${config.my.user}/nix-config";
      defaultText = lib.literalExpression ''"/home/''${config.my.user}/nix-config"'';
      description = "Where this repository is checked out on the machine.";
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
