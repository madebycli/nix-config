{ lib, pkgs, ... }:

let
  managedPackages = [
    "app.twintaillauncher.ttl"
    "com.github.tchx84.Flatseal"
    "gg.norisk.NoRiskClientLauncherV3"
    "io.mrarm.mcpelauncher"
    "moe.launcher.sleepy-launcher"
    "moe.launcher.the-honkers-railway-launcher"
  ];

  packageArguments =
    lib.concatStringsSep " " (map lib.escapeShellArg managedPackages);
in
{
  services.flatpak.enable = true;

  # Installiert fehlende deklarierte Anwendungen, entfernt aber keine
  # zusätzlich manuell installierten Flatpaks.
  systemd.services.flatpak-declarative = {
    description =
      "Install declared system Flatpaks while preserving unmanaged apps";

    wants = [ "network-online.target" ];

    after = [
      "network-online.target"
      "flatpak-system-helper.service"
    ];

    serviceConfig.Type = "oneshot";
    path = [ pkgs.flatpak ];

    script = ''
      flatpak remote-add \
        --system \
        --if-not-exists \
        flathub \
        https://dl.flathub.org/repo/flathub.flatpakrepo

      for package in ${packageArguments}; do
        if ! flatpak info --system "$package" >/dev/null 2>&1; then
          flatpak install \
            --system \
            --noninteractive \
            -y \
            flathub \
            "$package"
        fi
      done
    '';
  };

  systemd.timers.flatpak-declarative = {
    description = "Install declared Flatpaks after boot and daily";
    wantedBy = [ "timers.target" ];

    timerConfig = {
      OnBootSec = "30s";
      OnUnitInactiveSec = "1d";
    };
  };

  systemd.services.flatpak-update = {
    description = "Update system Flatpaks";

    wants = [
      "network-online.target"
      "flatpak-declarative.service"
    ];

    after = [
      "network-online.target"
      "flatpak-system-helper.service"
      "flatpak-declarative.service"
    ];

    serviceConfig.Type = "oneshot";
    path = [ pkgs.flatpak ];

    script = ''
      flatpak update \
        --system \
        --noninteractive \
        -y
    '';
  };

  systemd.timers.flatpak-update = {
    description = "Update Flatpaks after boot and daily";
    wantedBy = [ "timers.target" ];

    timerConfig = {
      OnBootSec = "1min";
      OnCalendar = "daily";
      Persistent = true;
    };
  };
}
