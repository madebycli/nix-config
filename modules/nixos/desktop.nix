{ config, pkgs, lib, ... }:

let
  # Keep all desktop-entry roots in the session environment. The portal module
  # and display-manager session packages can otherwise leave XDG_DATA_DIRS
  # pointing only at generated session metadata, while Flatpak adds its own
  # export roots. Fuzzel and Noctalia both discover applications through this
  # variable.
  launcherDataDirs = lib.concatStringsSep ":" [
    "/run/current-system/sw/share"
    "/nix/var/nix/profiles/default/share"
    "/etc/profiles/per-user/xxxxx/share"
    "/home/xxxxx/.nix-profile/share"
    "/home/xxxxx/.local/share"
    "/home/xxxxx/.local/share/flatpak/exports/share"
    "/var/lib/flatpak/exports/share"
    "/usr/local/share"
    "/usr/share"
  ];

  portalPreferences = pkgs.writeText "browser-portal-file-picker.js" ''
    pref("widget.use-xdg-desktop-portal.file-picker", 1);
  '';

  librewolfWithPortal = pkgs.librewolf.override {
    extraPrefsFiles = (pkgs.librewolf-unwrapped.extraPrefsFiles or [ ]) ++ [
      portalPreferences
    ];
  };
in

{
  # Keep native NixOS, user-profile, and Flatpak desktop entries visible to
  # every graphical session. MangoWM repeats this at compositor level because
  # Mango resets env= values on config reload.
  environment.sessionVariables.XDG_DATA_DIRS = lib.mkForce launcherDataDirs;

  programs.firefox = {
    enable = true;
    preferences = {
      # Force Firefox to use the portal FileChooser backend, which is mapped
      # independently from MangoWM's wlroots ScreenCast backend.
      "widget.use-xdg-desktop-portal.file-picker" = 1;
    };
  };

  xdg.portal = {
    enable = true;
    extraPortals = [
      pkgs.xdg-desktop-portal-gtk
      pkgs.xdg-desktop-portal-gnome
      pkgs.xdg-desktop-portal-wlr
    ];
    config.common = {
      default = [ "gtk" ];
      "org.freedesktop.impl.portal.FileChooser" = [ "gnome" ];
      "org.freedesktop.impl.portal.ScreenCast" = [ "wlr" ];
      "org.freedesktop.impl.portal.Screenshot" = [ "wlr" ];
      "org.freedesktop.impl.portal.Inhibit" = [ "none" ];
    };
  };

  services.gnome.sushi.enable = true;

  fonts = {
    enableDefaultPackages = true;
    packages = with pkgs; [
      nerd-fonts.jetbrains-mono
      inter
      corefonts
    ];
    fontconfig = {
      enable = true;
      defaultFonts = {
        sansSerif = [
          "Inter"
          "Noto Sans"
        ];
        serif = [ "Noto Serif" ];
        monospace = [ "JetBrainsMono Nerd Font" ];
      };
    };
    fontDir.enable = true;
  };

  environment.systemPackages = with pkgs; [
    xwayland-satellite
    ghostty
    bazaar

    mangohud
    protonup-ng
    umu-launcher
    lutris
    goverlay
    heroic

    winetricks
    wineWow64Packages.waylandFull
    mpv
    ffmpeg
    gpu-screen-recorder
    gpu-screen-recorder-gtk
    cava

    nautilus

    appimage-run
    unrar
    unzip

    btop
    resources
    fuzzel
    lxqt.lxqt-policykit
    git
    gh
    jq

    (python3.withPackages (pythonPackages: with pythonPackages; [
      pygobject3
      pillow
    ]))
    gtk3
    gtk-layer-shell
    gobject-introspection

    adw-gtk3
    tela-circle-icon-theme
    nwg-look
    google-cursor

    libreoffice-fresh
    hunspell
    hunspellDicts.de_DE
    hyphenDicts.de_DE
    papers
    loupe

    brave
    librewolfWithPortal
    joplin-desktop
    protonplus
    vesktop
    pavucontrol
    faugus-launcher
    gnome-clocks
    gnome-calendar
    gnome-calculator
    gnome-disk-utility
    gnome-text-editor
    proton-pass

    fastfetch
    yazi
    tree
    xed-editor
    komikku
    prismlauncher
  ];

  nixpkgs.config.allowInsecurePredicate = pkg: lib.getName pkg == "electron";
}
