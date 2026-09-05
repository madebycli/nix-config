{ stdenvNoCC }:

stdenvNoCC.mkDerivation {
  pname = "plymouth-theme-plmf-zoot";
  version = "0.1.0";
  src = ./.;

  dontBuild = true;

  installPhase = ''
    runHook preInstall

    install -Dm0644 zoot.plymouth \
      "$out/share/plymouth/themes/zoot/zoot.plymouth"
    install -Dm0644 zoot.script \
      "$out/share/plymouth/themes/zoot/zoot.script"

    runHook postInstall
  '';
}
