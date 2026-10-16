{ config, lib, pkgs, ... }:

let
  cfg = config.my.features.dots;
  dots = pkgs.callPackage ../../pkgs/dots { };
in
{
  options.my.features.dots = {
    enable = lib.mkEnableOption "dots: Git-based synchronisation of app configuration between machines";

    apps = lib.mkOption {
      type = lib.types.listOf lib.types.str;
      default = [ "mango" "niri" "hypr" "noctalia" "caelestia" ];
      description = ''
        Folders of ~/.config that live in <repo>/config/<name> and are linked
        back into ~/.config. Edits take effect immediately and show up as Git
        changes; `dots on` pushes and pulls them automatically.
      '';
    };

    interval = lib.mkOption {
      type = lib.types.str;
      default = "5min";
      description = "How often the timer runs while auto-sync is on.";
    };
  };

  config = lib.mkIf cfg.enable {
    environment.systemPackages = [ dots ];

    environment.etc."dots.conf".text = ''
      REPO=${lib.escapeShellArg config.my.repoPath}
      APPS=${lib.escapeShellArg (lib.concatStringsSep " " cfg.apps)}
    '';

    systemd.user.services = {
      # Recreates the ~/.config links at every login.
      dots-link = {
        description = "Link managed config folders into ~/.config";
        wantedBy = [ "default.target" ];
        serviceConfig = {
          Type = "oneshot";
          ExecStart = "${lib.getExe dots} link";
        };
      };

      # Does nothing unless `dots on` created the flag file.
      dots-sync = {
        description = "Synchronise managed config with Git (if switched on)";
        after = [ "network-online.target" ];
        serviceConfig = {
          Type = "oneshot";
          ExecStart = "${lib.getExe dots} auto";
        };
      };
    };

    systemd.user.timers.dots-sync = {
      description = "Periodic dots synchronisation";
      wantedBy = [ "timers.target" ];
      timerConfig = {
        OnStartupSec = "2min";
        OnUnitActiveSec = cfg.interval;
      };
    };
  };
}
