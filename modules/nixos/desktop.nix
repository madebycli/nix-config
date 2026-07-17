{ config, pkgs, lib, ... }:

{
  xdg.portal = {
    enable = true;
    extraPortals = [
      pkgs.xdg-desktop-portal-gtk
      pkgs.xdg-desktop-portal-wlr
    ];
    config.common = {
      default = [ "gtk" ];
      "org.freedesktop.impl.portal.ScreenCast" = [ "wlr" ];
      "org.freedesktop.impl.portal.Screenshot" = [ "wlr" ];
      "org.freedesktop.impl.portal.Inhibit" = [ "none" ];
    };
  };

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
    librewolf
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
