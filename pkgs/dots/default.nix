{ lib, writeShellApplication, git, coreutils, findutils, gnused, hostname, libnotify }:

writeShellApplication {
  name = "dots";
  runtimeInputs = [ git coreutils findutils gnused hostname libnotify ];
  text = builtins.readFile ./dots.sh;
  meta.mainProgram = "dots";
}
