{ config, lib, pkgs, ... }:
let
  cfg = config.my.features.local-ai;
  packages = import ../../pkgs/aibox { inherit pkgs lib; inherit (cfg) agentExtraPackages; };
in
{
  options.my.features.local-ai = {
    enable = lib.mkEnableOption "on-demand rootless llama.cpp/Strata HIP and workspace coding containers, without models";
    defaultProfile = lib.mkOption {
      type = lib.types.enum [ "qwen27-iq4xs" "bonsai27-pq2" ];
      default = "qwen27-iq4xs";
      description = "Pinned model selected by aibox start/ui/fetch. Models are downloaded only by explicit fetch.";
    };
    contextSize = lib.mkOption {
      type = lib.types.ints.between 2048 262144;
      default = 16384;
      description = "Explicit context per single inference slot. K/V caches are q8_0; MTP max draft depth is 2. Allocation failure does not reduce context or offload weights automatically.";
    };
    longContext = lib.mkOption {
      description = ''
        Optional KVMem long-context test mode (aibox prepare --kvmem; aibox ui --long-context lc64|lc128|lc256|lc512).
        Does nothing unless selected on the command line; the 16K Prism path stays the default and rollback.
        Null values keep the preset; nothing is ever reduced automatically when memory is short.
      '';
      default = { };
      type = lib.types.submodule {
        options = {
          gpuBudget = lib.mkOption { type = lib.types.nullOr lib.types.ints.positive; default = null; description = "VRAM KV history window (tokens, multiple of 128)."; };
          genReserve = lib.mkOption { type = lib.types.nullOr lib.types.ints.positive; default = null; description = "VRAM KV generation workspace (tokens, multiple of 128)."; };
          hostKvMiB = lib.mkOption { type = lib.types.nullOr lib.types.ints.positive; default = null; description = "Hard KVMem host-RAM KV quota in MiB."; };
          containerRamMiB = lib.mkOption { type = lib.types.nullOr lib.types.ints.positive; default = null; description = "Hard container RAM cap in MiB; swap is disabled for it."; };
          kvDtype = lib.mkOption { type = lib.types.nullOr (lib.types.enum [ "q8_0" "q5_0" ]); default = null; description = "KV cache type for long-context mode. Null keeps the requested q8_0; q5_0 is an explicit opt-in (the KVMem IQ4 reference recipe) that frees VRAM for a larger window."; };
          vramHeadroomMiB = lib.mkOption { type = lib.types.ints.unsigned; default = 256; description = "Free VRAM required beyond the estimate before start."; };
          ramHeadroomMiB = lib.mkOption { type = lib.types.ints.unsigned; default = 2048; description = "Free host RAM required beyond the container cap before start."; };
        };
      };
    };
    gpuArch = lib.mkOption {
      type = lib.types.enum [ "gfx1030" "gfx1100" "gfx1101" "gfx1200" "gfx1201" ];
      default = "gfx1030";
      description = "HIP compile target. gfx1030 is RX 6800/6900; hardware acceptance remains required.";
    };
    renderDevice = lib.mkOption {
      type = lib.types.strMatching "/dev/dri/renderD[0-9]+";
      default = "/dev/dri/renderD128";
      description = "Only this render node plus /dev/kfd is shared with inference. Verify on multi-GPU hosts.";
    };
    modelDirectory = lib.mkOption {
      type = lib.types.str;
      default = "/home/${config.my.user}/.local/share/nx-ai/models";
      defaultText = lib.literalExpression ''"/home/''${config.my.user}/.local/share/nx-ai/models"'';
      description = "Model storage: read-only for aibox start, writable for the explicit full model manager. Nothing is downloaded or started by activation.";
    };
    hipBaseImage = lib.mkOption {
      type = lib.types.str;
      default = "docker.io/rocm/dev-ubuntu-24.04:7.2.3-complete";
      description = "ROCm build image used only by explicit aibox prepare. A registry digest may be supplied.";
    };
    buildJobs = lib.mkOption {
      type = lib.types.ints.between 1 64;
      default = 2;
      description = "Parallel engine compilation jobs during explicit preparation, not an inference CPU limit.";
    };
    agentExtraPackages = lib.mkOption {
      type = lib.types.listOf lib.types.package;
      default = [ ];
      description = "Additional tools baked into the isolated coding image, never host bind mounts.";
    };
  };
  config = lib.mkIf cfg.enable {
    virtualisation.podman = {
      enable = true;
      dockerCompat = false;
      defaultNetwork.settings.dns_enabled = true;
    };
    users.users.${config.my.user} = {
      autoSubUidGidRange = true;
      extraGroups = [ "render" "video" ];
    };
    environment.systemPackages = [ packages.aibox ];
    # Podman's NixOS module normally enables both API sockets. This controller
    # uses the local CLI only and must not activate a rootful or user API service.
    systemd.sockets.podman.enable = false;
    systemd.services.podman.enable = false;
    systemd.user.sockets.podman.enable = false;
    systemd.user.services.podman.enable = false;
    environment.etc."aibox.json".text = builtins.toJSON {
      inherit (cfg) gpuArch renderDevice modelDirectory hipBaseImage buildJobs defaultProfile contextSize longContext;
    };
  };
}
