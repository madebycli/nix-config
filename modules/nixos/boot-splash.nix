{ config, lib, pkgs, ... }:

let
  cfg = config.plmf.bootSplash;

  builtInThemes = {
    minimal = {
      package = pkgs.callPackage ../../themes/plymouth/minimal { };
      description = "Minimal PLMF boot splash";
    };
    zoot = {
      package = pkgs.callPackage ../../themes/plymouth/zoot { };
      description = "ZOOT-inspired responsive terminal boot sequence";
    };
  };

  themeNames = builtins.attrNames cfg.themes;
  themePackages = map (name: cfg.themes.${name}.package) themeNames;
  validThemeName = name:
    builtins.match "^[A-Za-z0-9][A-Za-z0-9._-]*$" name != null;

  allowedThemesText = lib.concatStringsSep "\n" themeNames + "\n";
  metadataText =
    lib.concatMapStringsSep "\n"
      (name: "${name}\t${cfg.themes.${name}.description}")
      themeNames
    + "\n";

  allowedThemesFile = pkgs.writeText "plmf-allowed-themes" allowedThemesText;
  defaultThemeFile = pkgs.writeText "plmf-default-theme" "${cfg.defaultTheme}\n";
  metadataFile = pkgs.writeText "plmf-theme-metadata" metadataText;
  selectorRelativeFile = pkgs.writeText "plmf-selector-relative-path" "${cfg.selectorRelativePath}\n";

  efiMountPoint = config.boot.loader.efi.efiSysMountPoint;
  hasEfiFileSystem = builtins.hasAttr efiMountPoint config.fileSystems;
  efiFileSystem =
    if hasEfiFileSystem then
      config.fileSystems.${efiMountPoint}
    else
      { device = ""; fsType = ""; };
  efiDevice = efiFileSystem.device or "";
  efiFsType = efiFileSystem.fsType or "";
  efiMountPointFile = pkgs.writeText "plmf-efi-mount-point" "${efiMountPoint}\n";

  themeBundle = pkgs.runCommand "plmf-plymouth-initrd-themes" { } ''
    set -euo pipefail
    mkdir -p "$out"

    ${lib.concatMapStringsSep "\n" (name: ''
      test -d "${cfg.themes.${name}.package}/share/plymouth/themes/${name}"
      cp -a \
        "${cfg.themes.${name}.package}/share/plymouth/themes/${name}" \
        "$out/${name}"
    '') themeNames}
  '';

  # Only plugins from the configured Plymouth package are admitted to the initrd.
  # Theme packages can provide data and scripts, but cannot smuggle native plugins.
  pluginBundle = pkgs.runCommand "plmf-plymouth-initrd-plugins" { } ''
    set -euo pipefail
    mkdir -p "$out/renderers"
    cp -a "${config.boot.plymouth.package}/lib/plymouth/"*.so "$out/"
    cp -a "${config.boot.plymouth.package}/lib/plymouth/renderers/"*.so "$out/renderers/"
    rm -f "$out/renderers/x11.so"
  '';

  testSource = lib.cleanSource ../..;
  plmfProgram = pkgs.writeShellApplication {
    name = "plmf";
    runtimeInputs = with pkgs; [
      coreutils
      diffutils
      findutils
      gawk
      gnugrep
      nix
      util-linux
    ];
    text = ''
      export PLMF_TEST_NIX=${lib.escapeShellArg "${testSource}/tests/boot-splash-vm.nix"}
      ${builtins.readFile ../../scripts/plmf.sh}
    '';
  };

in
{
  options.plmf.bootSplash = {
    enable = lib.mkEnableOption "PLMF Plymouth boot splash";

    defaultTheme = lib.mkOption {
      type = lib.types.str;
      default = "minimal";
      description = "Declarative Plymouth theme used when no valid runtime override is active.";
    };

    themes = lib.mkOption {
      type = lib.types.attrsOf (lib.types.submodule {
        options = {
          package = lib.mkOption {
            type = lib.types.package;
            description = "Package containing share/plymouth/themes/<name>.";
          };
          description = lib.mkOption {
            type = lib.types.singleLineStr;
            default = "";
            description = "Local description used by plmf theme list/search.";
          };
        };
      });
      default = builtInThemes;
      description = "Build-time allowlist of Plymouth themes bundled into the initrd.";
    };

    selectorRelativePath = lib.mkOption {
      type = lib.types.str;
      default = "EFI/PLMF/theme";
      description = "Trusted path on the EFI system partition for the runtime theme selector.";
    };
  };

  config = lib.mkIf cfg.enable {
    assertions = [
      {
        assertion = themeNames != [ ];
        message = "plmf.bootSplash.themes must contain at least one bundled theme.";
      }
      {
        assertion = builtins.all validThemeName themeNames;
        message = "PLMF theme names may only contain letters, digits, dot, underscore, and hyphen.";
      }
      {
        assertion = builtins.elem cfg.defaultTheme themeNames;
        message = "plmf.bootSplash.defaultTheme must be present in plmf.bootSplash.themes.";
      }
      {
        assertion =
          cfg.selectorRelativePath != ""
          && !(lib.hasPrefix "/" cfg.selectorRelativePath)
          && !(lib.hasInfix ".." cfg.selectorRelativePath)
          && builtins.match "^[A-Za-z0-9._/-]+$" cfg.selectorRelativePath != null;
        message = "plmf.bootSplash.selectorRelativePath must be a safe relative ESP path.";
      }
      {
        assertion = hasEfiFileSystem;
        message = "PLMF boot splash needs fileSystems.${efiMountPoint} so the ESP device can be derived declaratively.";
      }
      {
        assertion = efiDevice != "" && efiFsType != "";
        message = "PLMF boot splash needs an ESP device and fsType at fileSystems.${efiMountPoint}.";
      }
    ];

    boot = {
      plymouth = {
        enable = true;
        showDelay = 0;
        theme = cfg.defaultTheme;
        themePackages = themePackages;
      };

      initrd = {
        supportedFilesystems = lib.optional (efiFsType != "") efiFsType;

        systemd = {
          contents = {
            "/etc/plmf/allowed-themes".source = allowedThemesFile;
            "/etc/plmf/default-theme".source = defaultThemeFile;
            "/etc/plmf/theme-metadata".source = metadataFile;
            "/etc/plmf/efi-mount-point".source = efiMountPointFile;
            "/etc/plmf/selector-relative-path".source = selectorRelativeFile;

            "/etc/plymouth/themes".source = lib.mkForce themeBundle;
            "/etc/plymouth/plugins".source = lib.mkForce pluginBundle;
          };

          services = {
            plmf-select-theme = {
              description = "Select trusted PLMF Plymouth theme";
              wantedBy = [ "sysinit.target" ];
              before = [ "plymouth-start.service" ];
              after = [ "systemd-udev-trigger.service" ];
              path = with pkgs; [ coreutils diffutils util-linux ];
              serviceConfig = {
                Type = "oneshot";
                TimeoutStartSec = "7s";
              };
              script = ''
                set -u

                default_theme=$(cat /etc/plmf/default-theme)
                effective_theme="$default_theme"
                esp_mount=/run/plmf-esp
                selector="$esp_mount/${cfg.selectorRelativePath}"
                mounted=0

                mkdir -p /run/plmf "$esp_mount"

                if timeout 3s mount \
                  -t ${lib.escapeShellArg efiFsType} \
                  -o ro,nosuid,nodev,noexec \
                  ${lib.escapeShellArg efiDevice} \
                  "$esp_mount"; then
                  mounted=1

                  if [ -f "$selector" ]; then
                    selector_size=$(stat -c '%s' -- "$selector" 2>/dev/null || printf '999999')
                    if [ "$selector_size" -le 128 ] 2>/dev/null; then
                      while IFS= read -r candidate; do
                        [ -n "$candidate" ] || continue
                        if printf '%s\n' "$candidate" | cmp -s - "$selector"; then
                          effective_theme="$candidate"
                          break
                        fi
                      done < /etc/plmf/allowed-themes
                    fi
                  fi
                fi

                if [ "$mounted" -eq 1 ]; then
                  timeout 2s umount "$esp_mount" >/dev/null 2>&1 || \
                    umount -l "$esp_mount" >/dev/null 2>&1 || true
                fi

                printf '%s\n' "$effective_theme" > /run/plmf/effective-theme
                cat > /run/plmf/plymouthd.conf <<EOF
                [Daemon]
                ShowDelay=0
                DeviceTimeout=8
                Theme=$effective_theme
                EOF

                rm -f /etc/plymouth/plymouthd.conf
                ln -s /run/plmf/plymouthd.conf /etc/plymouth/plymouthd.conf

                exit 0
              '';
            };

            plymouth-start = {
              wants = [ "plmf-select-theme.service" ];
              after = [ "plmf-select-theme.service" ];
            };
          };
        };
      };
    };

    environment = {
      systemPackages = [ plmfProgram ];

      etc = {
        "plmf/allowed-themes".source = allowedThemesFile;
        "plmf/default-theme".source = defaultThemeFile;
        "plmf/theme-metadata".source = metadataFile;
        "plmf/efi-mount-point".source = efiMountPointFile;
        "plmf/selector-relative-path".source = selectorRelativeFile;
      };
    };
  };
}
