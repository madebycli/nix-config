{ config, pkgs, ... }:

let
  appDir =
    "${config.home.homeDirectory}/.local/share/appimages";

  appPath =
    "${appDir}/helium.AppImage";

  versionFile =
    "${appDir}/helium.version";

  updateHelium = pkgs.writeShellApplication {
    name = "update-helium-appimage";

    runtimeInputs = [
      pkgs.coreutils
      pkgs.curl
      pkgs.python3
    ];

    text = ''
      set -euo pipefail

      api_url="https://api.github.com/repos/imputnet/helium-linux/releases/latest"

      mkdir -p "${appDir}"

      release_json="$(
        curl \
          --fail \
          --silent \
          --show-error \
          --location \
          --retry 3 \
          --retry-all-errors \
          "$api_url"
      )"

      version="$(
        printf '%s' "$release_json" |
          python3 -c '
      import json
      import sys

      release = json.load(sys.stdin)
      print(release["tag_name"])
      '
      )"

      asset_url="$(
        printf '%s' "$release_json" |
          python3 -c '
      import json
      import sys

      release = json.load(sys.stdin)

      matches = [
          asset["browser_download_url"]
          for asset in release["assets"]
          if asset["name"].endswith("-x86_64.AppImage")
      ]

      if len(matches) != 1:
          raise SystemExit(
              f"Expected exactly one x86_64 AppImage, found {len(matches)}"
          )

      print(matches[0])
      '
      )"

      current_version=""

      if test -f "${versionFile}"; then
        current_version="$(cat "${versionFile}")"
      fi

      if test "$current_version" = "$version" \
        && test -x "${appPath}"
      then
        echo "Helium $version is already installed."
        exit 0
      fi

      temporary_file="$(
        mktemp "${appDir}/.helium.AppImage.XXXXXX"
      )"

      cleanup() {
        rm -f "$temporary_file"
      }

      trap cleanup EXIT

      echo "Downloading Helium $version..."

      curl \
        --fail \
        --show-error \
        --location \
        --retry 3 \
        --retry-all-errors \
        --output "$temporary_file" \
        "$asset_url"

      chmod 0755 "$temporary_file"
      mv -f "$temporary_file" "${appPath}"

      printf '%s\n' "$version" > "${versionFile}"

      trap - EXIT

      echo "Helium $version was installed successfully."
    '';
  };
in
{
  home.packages = [
    pkgs.appimage-run
    updateHelium
  ];

  xdg.desktopEntries.helium = {
    name = "Helium";
    genericName = "Web Browser";

    exec =
      "${pkgs.appimage-run}/bin/appimage-run ${appPath} %U";

    icon =
      "${config.home.homeDirectory}/AppImages/.icons/helium.png";

    terminal = false;

    categories = [
      "Network"
      "WebBrowser"
    ];

    type = "Application";
  };

  systemd.user.services.helium-appimage-update = {
    Unit = {
      Description = "Download the latest Helium AppImage";
      After = [ "network-online.target" ];
    };

    Service = {
      Type = "oneshot";
      ExecStart = "${updateHelium}/bin/update-helium-appimage";
    };
  };

  systemd.user.timers.helium-appimage-update = {
    Unit.Description =
      "Check for Helium updates after login and daily";

    Timer = {
      OnStartupSec = "1min";
      OnCalendar = "daily";
      Persistent = true;
      RandomizedDelaySec = "15min";
      Unit = "helium-appimage-update.service";
    };

    Install.WantedBy = [ "timers.target" ];
  };
}
