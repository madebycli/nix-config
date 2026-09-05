{ config, lib, ... }:

let
  cfg = config.plmf.bootSplash;
in
{
  options.plmf.bootSplash = {
    enable = lib.mkEnableOption "PLMF Plymouth boot splash";

    defaultTheme = lib.mkOption {
      type = lib.types.str;
      default = "bgrt";
      description = "Declarative Plymouth theme used when no runtime override is active.";
    };
  };

  config = lib.mkIf cfg.enable {
    boot.plymouth = {
      enable = true;
      showDelay = 0;
      theme = cfg.defaultTheme;
    };
  };
}
