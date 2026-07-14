{ inputs, ... }:

{
  imports = [
    inputs.noctalia.nixosModules.default
  ];

  programs.noctalia = {
    enable = true;
    recommendedServices.enable = false;
    systemd.enable = false;
  };
}
