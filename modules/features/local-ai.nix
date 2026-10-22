{ config, lib, pkgs, ... }:
let
  cfg = config.my.features.local-ai;
  packages = import ../../pkgs/aibox { inherit pkgs lib; inherit (cfg) agentExtraPackages; };
in
{
  options.my.features.local-ai = {
    enable = lib.mkEnableOption "on-demand rootless Strata HIP and workspace coding containers, without models";
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
      inherit (cfg) gpuArch renderDevice modelDirectory hipBaseImage buildJobs;
    };
  };
}
