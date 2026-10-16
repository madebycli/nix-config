{ stdenvNoCC }:

stdenvNoCC.mkDerivation {
  pname = "plymouth-theme-plmf-minimal";
  version = "1.0.0";
  src = ./.;

  dontBuild = true;

  installPhase = ''
    runHook preInstall

    install -Dm0644 minimal.plymouth \
      "$out/share/plymouth/themes/minimal/minimal.plymouth"
    install -Dm0644 minimal.script \
      "$out/share/plymouth/themes/minimal/minimal.script"

    runHook postInstall
  '';
}
