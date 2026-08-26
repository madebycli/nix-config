{ config, lib, pkgs, ... }:

let
  defaultConfig = ../../config/home/.config/hypr/hyprland.conf;
in
{
  home.activation.hyprlandConfig = lib.hm.dag.entryAfter [ "linkGeneration" ] ''
    config_dir="${config.home.homeDirectory}/.config/hypr"
    config_file="$config_dir/hyprland.conf"

    if [ -L "$config_file" ]; then
      target="$(${pkgs.coreutils}/bin/readlink -f "$config_file" 2>/dev/null || true)"
      case "$target" in
        /nix/store/*)
          $DRY_RUN_CMD ${pkgs.coreutils}/bin/rm -f "$config_file"
          ;;
      esac
    fi

    if [ ! -e "$config_file" ]; then
      $DRY_RUN_CMD ${pkgs.coreutils}/bin/mkdir -p "$config_dir"
      $DRY_RUN_CMD ${pkgs.coreutils}/bin/cp ${defaultConfig} "$config_file"
      $DRY_RUN_CMD ${pkgs.coreutils}/bin/chmod u+w "$config_file"
    fi
  '';
}
