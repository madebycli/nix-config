{ pkgs, lib ? pkgs.lib, agentExtraPackages ? [ ] }:

let
  skills = pkgs.writeTextDir "share/aibox/SKILLS.md" (builtins.readFile ./SKILLS.md);
  agentRoot = pkgs.buildEnv {
    name = "aibox-agent-root";
    paths = with pkgs; [
      bashInteractive
      coreutils
      gitMinimal
      curl
      cacert
      jq
      python3
      nodejs
      ripgrep
      fd
      gnumake
      gcc
      codex
      skills
    ] ++ agentExtraPackages;
    pathsToLink = [ "/bin" "/share" "/etc" ];
  };
  agentImage = pkgs.dockerTools.buildLayeredImage {
    name = "localhost/nx-ai-agent";
    # Derived from the closure, so updates cannot silently reuse an old image tag.
    tag = builtins.substring 0 20 (builtins.hashString "sha256" (toString agentRoot));
    contents = [ agentRoot pkgs.dockerTools.fakeNss ];
    extraCommands = ''
      mkdir -p work home/agent tmp
      chmod 1777 tmp
    '';
    config = {
      Cmd = [ "/bin/bash" ];
      WorkingDir = "/work";
      Env = [
        "PATH=/bin"
        "HOME=/home/agent"
        "LANG=C.UTF-8"
        "SSL_CERT_FILE=/etc/ssl/certs/ca-bundle.crt"
        "CURL_CA_BUNDLE=/etc/ssl/certs/ca-bundle.crt"
      ];
    };
  };
  support = pkgs.runCommand "aibox-support" { } ''
    mkdir -p $out
    cp ${./Containerfile} $out/Containerfile
    cp ${./entrypoint.py} $out/entrypoint.py
    cp ${./ManagerContainerfile} $out/ManagerContainerfile
    cp ${./manager-bundle.py} $out/manager-bundle.py
  '';
  aibox = pkgs.writeShellApplication {
    name = "aibox";
    inheritPath = true;
    runtimeInputs = [ pkgs.python3 pkgs.podman pkgs.crun pkgs.xdg-utils ];
    text = ''
      export AIBOX_AGENT_ARCHIVE=${agentImage}
      export AIBOX_AGENT_IMAGE=${lib.escapeShellArg "${agentImage.imageName}:${agentImage.imageTag}"}
      export AIBOX_SUPPORT=${support}
      exec python3 -I ${./aibox.py} "$@"
    '';
    meta.mainProgram = "aibox";
  };
in
{ inherit aibox agentImage; }
