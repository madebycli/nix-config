{ config, lib, pkgs, ... }:

let
  cfg = config.my.features.rust-dev;
  settingsDefaults = {
    "rust-analyzer.server.path" = "/run/current-system/sw/bin/rust-analyzer";
    "rust-analyzer.cargo.sysrootSrc" = "/etc/rust-dev/rust-src";
    "rust-analyzer.check.command" = "clippy";
    "[rust]" = {
      "editor.defaultFormatter" = "rust-lang.rust-analyzer";
      "editor.formatOnSave" = true;
    };
  };
  defaultsFile = pkgs.writeText "rust-dev-codium-defaults.json" (builtins.toJSON settingsDefaults);
in
{
  options.my.features.rust-dev.enable = lib.mkEnableOption
    "Rust development and learning tools with VSCodium";

  config = lib.mkIf cfg.enable {
    # Use one Nixpkgs toolchain instead of mixing rustup and system binaries.
    environment.systemPackages = with pkgs; [
      rustc
      cargo
      rustfmt
      clippy
      rust-analyzer
      rustlings
      gcc
      pkg-config
    ];
    environment.etc."rust-dev/rust-src".source = pkgs.rustPlatform.rustLibSrc;
    environment.variables.RUST_SRC_PATH = "/etc/rust-dev/rust-src";

    home-manager.users.${config.my.user} = { config, lib, ... }: {
      programs.vscodium = {
        enable = true;
        package = pkgs.vscodium;
        mutableExtensionsDir = true;
        profiles.default.extensions = with pkgs.vscode-extensions; [
          rust-lang.rust-analyzer
          vadimcn.vscode-lldb
          tamasfe.even-better-toml
        ];
      };

      # Do not declare userSettings: the editor and theme picker must be able
      # to write settings.json. Convert the old managed link before HM's cleanup
      # removes it; subsequent activations preserve the user's file unchanged.
      home.activation.rustDevWritableSettings = lib.hm.dag.entryBetween
        [ "linkGeneration" ] [ "writeBoundary" ] ''
          run ${pkgs.python3}/bin/python3 ${./rust-dev-settings.py} \
            ${lib.escapeShellArg "${config.xdg.configHome}/VSCodium/User/settings.json"} \
            ${defaultsFile}
        '';
    };
  };
}
