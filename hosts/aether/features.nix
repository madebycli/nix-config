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
    plymouth = {
      enable = true;
      theme = "zoot"; # Arknights-style terminal; switch live: sudo plmf theme set <name>
    };
    sandbox.enable = true;
  };
}
