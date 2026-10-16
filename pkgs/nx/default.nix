{ lib, stdenvNoCC, python3, makeWrapper, git, nix, coreutils }:

stdenvNoCC.mkDerivation {
  pname = "nx";
  version = "1.0";
  src = ./.;
  dontBuild = true;
  nativeBuildInputs = [ makeWrapper ];

  installPhase = ''
    runHook preInstall
    install -Dm0755 nx.py $out/libexec/nx/nx.py
    makeWrapper ${python3}/bin/python3 $out/bin/nx \
      --add-flags "-I $out/libexec/nx/nx.py" \
      --prefix PATH : ${lib.makeBinPath [ git nix coreutils ]}
    install -Dm0644 completions/nx.fish $out/share/fish/vendor_completions.d/nx.fish
    install -Dm0644 completions/nx.bash $out/share/bash-completion/completions/nx
    runHook postInstall
  '';

  meta = {
    description = "Update, switch and housekeeping for this NixOS configuration";
    mainProgram = "nx";
    platforms = lib.platforms.linux;
  };
}
