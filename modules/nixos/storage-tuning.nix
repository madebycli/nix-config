{ config, hardwareConfigPath, lib, modulesPath, pkgs, ... }:

let
  generatedHardware = import hardwareConfigPath {
    inherit config lib modulesPath pkgs;
  };

  generatedLuksDevices = generatedHardware.boot.initrd.luks.devices or { };
in
{
  # Ergänzt automatisch jedes LUKS-Gerät aus der lokalen, vom Installer
  # übernommenen hardware-configuration.nix. Es muss keine UUID mehr manuell
  # in eine Hostdatei kopiert werden.
  boot.initrd.luks.devices = lib.mapAttrs (_name: _device: {
    bypassWorkqueues = true;
    allowDiscards = true;
  }) generatedLuksDevices;

  # Installer und config-update legen nach einem erfolgreichen Switch die Datei
  # /var/lib/nixos-config/fstrim-pending an. Erst beim folgenden Neustart ist
  # das Root-LUKS-Gerät mit den neuen Discard-Optionen geöffnet; dann läuft TRIM
  # genau einmal und die Markierung wird wieder entfernt.
  systemd.services.nixos-config-fstrim = {
    description = "Run pending TRIM after reboot";
    wantedBy = [ "multi-user.target" ];
    after = [ "local-fs.target" ];
    wants = [ "local-fs.target" ];

    unitConfig.ConditionPathExists = "/var/lib/nixos-config/fstrim-pending";

    serviceConfig = {
      Type = "oneshot";
      StateDirectory = "nixos-config";
    };

    script = ''
      ${pkgs.coreutils}/bin/sleep 10

      if ! ${pkgs.util-linux}/bin/fstrim -v /; then
        echo "Hinweis: fstrim für / wurde nicht unterstützt oder war nicht nötig." >&2
      fi

      ${pkgs.coreutils}/bin/rm -f /var/lib/nixos-config/fstrim-pending
    '';
  };
}
