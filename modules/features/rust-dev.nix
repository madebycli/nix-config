{ config, lib, pkgs, ... }:

let
  cfg = config.my.features.rust-dev;
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
    environment.variables.RUST_SRC_PATH = "${pkgs.rustPlatform.rustLibSrc}";

    home-manager.users.${config.my.user}.programs.vscodium = {
      enable = true;
      package = pkgs.vscodium;
      profiles.default = {
        extensions = with pkgs.vscode-extensions; [
          rust-lang.rust-analyzer
          vadimcn.vscode-lldb
          tamasfe.even-better-toml
        ];
        userSettings = {
          "rust-analyzer.server.path" = "${pkgs.rust-analyzer}/bin/rust-analyzer";
          "rust-analyzer.cargo.sysrootSrc" = "${pkgs.rustPlatform.rustLibSrc}";
          "rust-analyzer.check.command" = "clippy";
          "[rust]" = {
            "editor.defaultFormatter" = "rust-lang.rust-analyzer";
            "editor.formatOnSave" = true;
          };
        };
      };
    };
  };
}
