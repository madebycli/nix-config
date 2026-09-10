{ hostName, lib, pkgs, ... }:

let
  aetherAudioSnapshot = pkgs.writeShellApplication {
    name = "aether-audio-snapshot";
    runtimeInputs = with pkgs; [
      coreutils
      gawk
      gnused
      pipewire
      systemd
      wireplumber
    ];
    text = builtins.readFile ../../scripts/aether-audio-snapshot.sh;
  };
in
{
  environment.systemPackages = lib.optional (hostName == "aether") aetherAudioSnapshot;
}
