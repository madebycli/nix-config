# Feature switches for this machine, one setting per line.
# `nixctl` edits the `.enable = ...;` lines and the my.desktop lines;
# everything else can be changed by hand.
{
  my.kernel = "latest";

  my.desktop.compositors = [ "mango" ];
  my.desktop.defaultSession = "mango";
  my.desktop.shell = "noctalia";

  my.features.dots.enable = true;
  my.features.flatpak.enable = true;
  my.features.gaming.enable = true;
  my.features.virtualisation.enable = false;

  my.features.plymouth.enable = true;
  my.features.plymouth.theme = "zoot"; # Arknights-style terminal; live switch: sudo plmf theme set <name>

  # Needs at least one public key before it can be switched on:
  my.features.agentbox.enable = false;
  # my.features.agentbox.sshKeys = [ "ssh-ed25519 AAAA... you@host" ];

  my.features.ai.enable = false;
  # Opt-in; adjust gpuArch/renderDevice for this machine before use.
  my.features.local-ai.enable = false;
}
