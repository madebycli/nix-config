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

  # Läuft nach Aktivierung eines neuen Systems sowie bei jedem Start. Ein
  # fehlendes TRIM-Feature blockiert weder Boot noch nixos-rebuild switch.
  systemd.services.nixos-config-fstrim = {
    description = "TRIM root filesystem after NixOS activation";
    wantedBy = [ "multi-user.target" ];
    after = [ "local-fs.target" ];
    wants = [ "local-fs.target" ];
    restartIfChanged = true;

    serviceConfig.Type = "oneshot";

    script = ''
      ${pkgs.coreutils}/bin/sleep 10
      if ! ${pkgs.util-linux}/bin/fstrim -v /; then
        echo "Hinweis: fstrim für / wurde nicht unterstützt oder war nicht nötig." >&2
      fi
    '';
  };
}
