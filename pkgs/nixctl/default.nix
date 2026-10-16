{ writeShellApplication, coreutils, gawk, gnugrep, gnused, git, gum, nix }:

writeShellApplication {
  name = "nixctl";
  runtimeInputs = [ coreutils gawk gnugrep gnused git gum nix ];
  # nixos-rebuild and sudo come from the system.
  inheritPath = true;
  text = builtins.readFile ./nixctl.sh;
  meta.mainProgram = "nixctl";
}
