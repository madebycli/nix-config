{ config, lib, pkgs, ... }:

let
  cfg = config.my.features.sandbox;

  gbox = pkgs.callPackage ../../pkgs/gbox {
    extraPackages = with pkgs; [
      wineWow64Packages.waylandFull
      winetricks
      umu-launcher
      mangohud
    ];
  };

  appModule = { name, ... }: {
    options = {
      command = lib.mkOption {
        type = lib.types.listOf lib.types.str;
        description = "Program and arguments started inside the sandbox.";
      };
      displayName = lib.mkOption {
        type = lib.types.str;
        default = name;
        description = "Name shown in the application menu.";
      };
      net = lib.mkOption {
        type = lib.types.enum [ "none" "inet" "lan" ];
        default = "none";
        description = "none: offline. inet: internet only. lan: internet and local network.";
      };
      display = lib.mkOption {
        type = lib.types.enum [ "gamescope" "wayland" "none" ];
        default = "gamescope";
      };
      gamescopeArgs = lib.mkOption {
        type = lib.types.str;
        default = "";
      };
      gpu = lib.mkOption { type = lib.types.bool; default = true; };
      audio = lib.mkOption { type = lib.types.bool; default = true; };
      hud = lib.mkOption { type = lib.types.bool; default = false; };
      share = lib.mkOption {
        type = lib.types.listOf lib.types.str;
        default = [ ];
        description = "Read-write folders, mounted at the same path.";
      };
      ro = lib.mkOption {
        type = lib.types.listOf lib.types.str;
        default = [ ];
        description = "Read-only folders, mounted at the same path.";
      };
      devices = lib.mkOption {
        type = lib.types.listOf lib.types.str;
        default = [ ];
        description = "Device nodes, e.g. a single gamepad event device.";
      };
      env = lib.mkOption {
        type = lib.types.attrsOf lib.types.str;
        default = { };
      };
    };
  };

  b2i = b: if b then "1" else "0";

  profileText = name: app: lib.concatStringsSep "\n" (
    [
      "# declared by NixOS (my.features.sandbox.apps.${name})"
      "net=${app.net}"
      "display=${app.display}"
      "gpu=${b2i app.gpu}"
      "audio=${b2i app.audio}"
      "hud=${b2i app.hud}"
    ]
    ++ lib.optional (app.gamescopeArgs != "") "gamescope-args=${app.gamescopeArgs}"
    ++ map (p: "share=${p}") app.share
    ++ map (p: "ro=${p}") app.ro
    ++ map (p: "dev=${p}") app.devices
    ++ lib.mapAttrsToList (k: v: "env=${k}=${v}") app.env
    ++ map (c: "cmd=${c}") app.command
  ) + "\n";

  launcher = name: app: pkgs.writeShellScriptBin "gbox-${name}" ''
    exec ${lib.getExe gbox} run ${lib.escapeShellArg name} -- "$@"
  '';
in
{
  options.my.features.sandbox = {
    enable = lib.mkEnableOption "gbox, the bubblewrap sandbox for games, Wine and untrusted programs";

    apps = lib.mkOption {
      type = lib.types.attrsOf (lib.types.submodule appModule);
      default = { };
      description = ''
        Declarative sandbox profiles. Each entry becomes
        /etc/gbox/profiles/NAME.conf, a `gbox-NAME` command and a menu entry.
        Ad-hoc profiles are created with `gbox new`.
      '';
    };
  };

  config = lib.mkIf cfg.enable {
    environment.systemPackages = [ gbox ]
      ++ lib.mapAttrsToList launcher cfg.apps
      ++ lib.mapAttrsToList
        (name: app: pkgs.makeDesktopItem {
          name = "gbox-${name}";
          desktopName = "${app.displayName} (sandboxed)";
          exec = "gbox run ${lib.escapeShellArg name}";
          categories = [ "Game" ];
        })
        cfg.apps;

    environment.etc = lib.mapAttrs'
      (name: app: lib.nameValuePair "gbox/profiles/${name}.conf" {
        text = profileText name app;
      })
      cfg.apps;

    # bubblewrap runs unprivileged on user namespaces; gamescope is the
    # host-side display proxy so sandboxed programs never see the real
    # Wayland socket.
    programs.gamescope.enable = true;
    security.allowUserNamespaces = true;
  };
}
