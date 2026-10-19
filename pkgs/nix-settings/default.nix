{ lib, rustPlatform, makeWrapper, rustfmt, nx, nixctl, dots, git, nix, bash, fastfetch }:

rustPlatform.buildRustPackage {
  pname = "nix-settings";
  version = "0.2.0";
  src = lib.cleanSource ../../nix-settings;
  cargoLock.lockFile = ../../nix-settings/Cargo.lock;
  nativeBuildInputs = [ makeWrapper ];
  nativeCheckInputs = [ rustfmt ];
  preBuild = ''
    # Cargo's writable cache belongs to this build, including without sandboxing.
    export CARGO_HOME="$TMPDIR/nix-settings-cargo-home"
    mkdir -p "$CARGO_HOME"
  '';
  preCheck = ''
    cargo fmt --all --check
  '';
  postInstall = ''
    wrapProgram "$out/bin/nix-settings" \
      --prefix PATH : ${lib.makeBinPath [ nx nixctl dots git nix bash fastfetch ]}
    ln -s nix-settings "$out/bin/nix-settings-tui"
    install -Dm444 ${../../THIRD_PARTY_NOTICES.md} "$out/share/licenses/nix-settings/THIRD_PARTY_NOTICES.md"
    install -Dm444 vendor/linutil-tui/LICENSE "$out/share/licenses/nix-settings/Linutil-MIT"
  '';
  meta = {
    description = "Rust terminal settings for nx, nixctl and dots";
    mainProgram = "nix-settings-tui";
    license = lib.licenses.mit;
    platforms = lib.platforms.linux;
  };
}
