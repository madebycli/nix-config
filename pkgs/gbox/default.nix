{ lib
, writeShellApplication
, bubblewrap
, passt
, nftables
, gamescope
, coreutils
, findutils
, gnugrep
, gnused
, util-linux
, bash
, extraPackages ? [ ]
}:

writeShellApplication {
  name = "gbox";
  runtimeInputs = [
    bubblewrap
    passt
    nftables
    gamescope
    coreutils
    findutils
    gnugrep
    gnused
    util-linux
    bash
  ] ++ extraPackages;
  text = builtins.readFile ./gbox.sh;
  meta = {
    description = "Sandbox for games, Wine prefixes and untrusted programs";
    mainProgram = "gbox";
    platforms = lib.platforms.linux;
  };
}
