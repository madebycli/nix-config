{ config, lib, ... }:

let
  cfg = config.my.desktop;
in
{
  imports = [
    ./apps.nix
    ./greeter.nix
    ./mango.nix
    ./niri.nix
    ./hyprland.nix
    ./noctalia.nix
    ./caelestia.nix
  ];

  options.my.desktop = {
    compositors = lib.mkOption {
      type = lib.types.nonEmptyListOf (lib.types.enum [ "mango" "niri" "hyprland" ]);
      default = [ "mango" ];
      description = "Wayland compositors installed side by side.";
    };

    defaultSession = lib.mkOption {
      type = lib.types.enum [ "mango" "niri" "hyprland" ];
      default = lib.head cfg.compositors;
      defaultText = lib.literalExpression "head config.my.desktop.compositors";
      description = "Compositor preselected by the greeter.";
    };

    shell = lib.mkOption {
      type = lib.types.enum [ "noctalia" "caelestia" ];
      default = "noctalia";
      description = ''
        Desktop shell. Caelestia is designed around Hyprland and is only
        allowed with the Hyprland-only compositor selection.
      '';
    };
  };

  config.services.gnome.gnome-keyring.enable = true;
  # Unlock the login keyring using the password supplied to the Noctalia greeter.
  config.security.pam.services.greetd.enableGnomeKeyring = true;
  config.services.gnome.gcr-ssh-agent.enable = true;

  config.assertions = [
    {
      assertion = lib.elem cfg.defaultSession cfg.compositors;
      message = "my.desktop.defaultSession must be one of my.desktop.compositors.";
    }
    {
      assertion = cfg.shell != "caelestia" || cfg.compositors == [ "hyprland" ];
      message = "Caelestia Shell is supported only with my.desktop.compositors = [ \"hyprland\" ].";
    }
  ];
}
