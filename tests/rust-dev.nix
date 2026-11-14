# Evaluate the real host integration and Home Manager profiles, without activation.
let
  flake = builtins.getFlake (toString ../.);
  lib = flake.inputs.nixpkgs.lib;
  normal = host: flake.nixosConfigurations."ci-${host}";
  full = host: flake.nixosConfigurations."ci-${host}-full";
  hasPackage = config: package:
    builtins.any (p: p.drvPath == package.drvPath) config.environment.systemPackages;
  disabled = host:
    let
      system = normal host;
      c = system.config;
    in
    !c.my.features.rust-dev.enable
    && !hasPackage c system.pkgs.rustc
    && !c.home-manager.users.${c.my.user}.programs.vscodium.enable
    && !(c.environment.variables ? RUST_SRC_PATH);
  enabled = host:
    let
      system = full host;
      c = system.config;
      pkgs = system.pkgs;
      home = c.home-manager.users.${c.my.user};
      editor = home.programs.vscodium;
      profile = editor.profiles.default;
      hasExtension = extension:
        builtins.any (p: p.drvPath == extension.drvPath) profile.extensions;
    in
    c.my.features.rust-dev.enable
    && builtins.all (hasPackage c) (with pkgs; [ rustc cargo rustfmt clippy rust-analyzer rustlings gcc pkg-config ])
    && c.environment.variables.RUST_SRC_PATH == "/etc/rust-dev/rust-src"
    && toString c.environment.etc."rust-dev/rust-src".source == "${pkgs.rustPlatform.rustLibSrc}"
    && !(builtins.hasAttr "${home.xdg.configHome}/VSCodium/User/settings.json" home.home.file)
    && !(builtins.hasAttr "${home.xdg.configHome}/Code/User/settings.json" home.home.file)
    && editor.enable
    && editor.mutableExtensionsDir
    && editor.package.drvPath == pkgs.vscodium.drvPath
    && builtins.all hasExtension (with pkgs.vscode-extensions; [
      rust-lang.rust-analyzer vadimcn.vscode-lldb tamasfe.even-better-toml
    ])
    && profile.userSettings == { }
    && home.home.activation.rustDevWritableSettings.before == [ "linkGeneration" ]
    && home.home.activation.rustDevWritableSettings.after == [ "writeBoundary" ];
in
{
  nyxDisabledByDefault = disabled "nyx";
  aetherDisabledByDefault = disabled "aether";
  nyxEnabledToolchainAndEditor = enabled "nyx";
  aetherEnabledToolchainAndEditor = enabled "aether";
}
