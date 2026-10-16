{ writeShellApplication, coreutils, gnugrep, openssh, systemd }:

writeShellApplication {
  name = "agentbox";
  runtimeInputs = [ coreutils gnugrep openssh systemd ];
  # sudo and codium come from the system / user profile.
  inheritPath = true;
  text = builtins.readFile ./agentbox.sh;
  meta.mainProgram = "agentbox";
}
