{ pkgs, lib ? pkgs.lib, agentExtraPackages ? [ ], agentToolsets ? [ ] }:

let
  # Screenshots for the agent: headless Chromium inside the container (no host display, no GPU).
  shot = pkgs.writeShellApplication {
    name = "shot";
    runtimeInputs = [ pkgs.chromium pkgs.coreutils ];
    text = ''
      if [ "$#" -lt 2 ]; then echo "usage: shot URL OUT.png [WIDTHxHEIGHT]" >&2; exit 2; fi
      size="''${3:-1280x800}"
      profile="$(mktemp -d)"
      chromium --headless=new --no-sandbox --disable-gpu --hide-scrollbars \
        --user-data-dir="$profile" --window-size="''${size%x*},''${size#*x}" \
        --virtual-time-budget=5000 --screenshot="$2" "$1"
    '';
  };
  toolsets = {
    web = [ pkgs.chromium shot ];
    jvm = [ pkgs.jdk21 pkgs.gradle pkgs.kotlin pkgs.maven ];
  };
  selectedTools = lib.concatMap (name: toolsets.${name} or (throw "unknown agent toolset ${name}")) agentToolsets;
  skills = pkgs.writeTextDir "share/aibox/SKILLS.md" (builtins.readFile ./SKILLS.md);
  probe = pkgs.writeTextDir "share/aibox/longctx_probe.py" (builtins.readFile ./longctx_probe.py);
  agentRoot = pkgs.buildEnv {
    name = "aibox-agent-root";
    paths = with pkgs; [
      bashInteractive
      coreutils
      gitMinimal
      curl
      cacert
      jq
      (python3.withPackages (ps: [ ps.pip ps.virtualenv ]))
      nodejs
      ripgrep
      fd
      gnumake
      gcc
      skills
      probe
    ] ++ selectedTools ++ agentExtraPackages;
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
    cp ${./LlamaContainerfile} $out/LlamaContainerfile
    cp ${./require-mtp.py} $out/require-mtp.py
    cp ${./KvmemContainerfile} $out/KvmemContainerfile
    cp ${./DevContainerfile} $out/DevContainerfile
    cp ${./shot.sh} $out/shot.sh
    cp ${./SKILLS.md} $out/SKILLS.md
    cp ${./longctx_probe.py} $out/longctx_probe.py
    cp ${./longcontext.json} $out/longcontext.json
    cp ${./profiles.json} $out/profiles.json
    cp ${./Containerfile} $out/Containerfile
    cp ${./entrypoint.py} $out/entrypoint.py
    cp ${./ManagerContainerfile} $out/ManagerContainerfile
    cp ${./manager-bundle.py} $out/manager-bundle.py
  '';
  aibox = pkgs.writeShellApplication {
    name = "aibox";
    inheritPath = true;
    runtimeInputs = [ pkgs.python3 pkgs.curl pkgs.podman pkgs.crun pkgs.xdg-utils ];
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
