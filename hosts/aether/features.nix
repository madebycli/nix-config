# Feature switches for this machine. `nixctl` edits the booleans below;
# everything else can be changed by hand.
{
  my.desktop = {
    compositors = [ "mango" ];
    defaultSession = "mango";
    shell = "noctalia";
  };

  my.features = {
    flatpak.enable = true;
    gaming.enable = true;
    sandbox.enable = true;
  };
}
