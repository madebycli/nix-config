{ config, lib, pkgs, ... }:

let
  cfg = config.my.features.ai;
  user = config.my.user;

  ollamaPackage = {
    rocm = pkgs.ollama-rocm;
    cuda = pkgs.ollama-cuda;
  }.${cfg.acceleration} or pkgs.ollama;

  services = [ "ollama.service" ] ++ lib.optional cfg.openWebui.enable "open-webui.service";

  ai = pkgs.writeShellApplication {
    name = "ai";
    inheritPath = true;
    runtimeInputs = [ pkgs.coreutils pkgs.systemd ];
    text = ''
      services=(${lib.concatStringsSep " " services})
      case "''${1:-status}" in
        on)
          sudo systemctl start "''${services[@]}"
          echo "ai: ollama on 127.0.0.1:11434${lib.optionalString cfg.openWebui.enable ", Open WebUI on http://127.0.0.1:${toString cfg.openWebui.port}"}"
          ;;
        off)
          sudo systemctl stop "''${services[@]}"
          echo "ai: stopped (GPU memory freed)"
          ;;
        ui)
          sudo systemctl start "''${services[@]}"
          xdg-open "http://127.0.0.1:${toString cfg.openWebui.port}"
          ;;
        status)
          for s in "''${services[@]}"; do
            printf '%-20s %s\n' "$s" "$(systemctl is-active "$s" || true)"
          done
          ;;
        *)
          echo "usage: ai [on|off|ui|status]" >&2
          exit 2
          ;;
      esac
    '';
  };
in
{
  options.my.features.ai = {
    enable = lib.mkEnableOption "local AI models (Ollama, optional Open WebUI), started on demand with `ai on`";

    acceleration = lib.mkOption {
      type = lib.types.nullOr (lib.types.enum [ "rocm" "cuda" ]);
      default = null;
      description = "GPU backend; null runs on the CPU.";
    };

    models = lib.mkOption {
      type = lib.types.listOf lib.types.str;
      default = [ ];
      example = [ "qwen3:8b" ];
      description = "Models pulled automatically whenever Ollama starts.";
    };

    openWebui = {
      enable = lib.mkOption { type = lib.types.bool; default = true; };
      port = lib.mkOption { type = lib.types.port; default = 8765; };
    };
  };

  config = lib.mkIf cfg.enable {
    services.ollama = {
      enable = true;
      package = ollamaPackage;
      host = "127.0.0.1";
      loadModels = cfg.models;
      environmentVariables = {
        OLLAMA_FLASH_ATTENTION = "1";
        OLLAMA_MAX_LOADED_MODELS = "1";
      };
    };

    services.open-webui = lib.mkIf cfg.openWebui.enable {
      enable = true;
      host = "127.0.0.1";
      port = cfg.openWebui.port;
      environment = {
        OLLAMA_API_BASE_URL = "http://127.0.0.1:11434";
        WEBUI_AUTH = "False";
        ANONYMIZED_TELEMETRY = "False";
        DO_NOT_TRACK = "True";
      };
    };

    # On demand: neither the model server nor its UI start with the system.
    systemd.services.ollama.wantedBy = lib.mkForce [ ];
    systemd.services.open-webui = lib.mkIf cfg.openWebui.enable {
      wantedBy = lib.mkForce [ ];
      wants = [ "ollama.service" ];
      after = [ "ollama.service" ];
    };

    environment.systemPackages = [ ai ];

    security.sudo.extraRules = [{
      users = [ user ];
      commands = lib.concatMap
        (action: map
          (service: {
            command = "/run/current-system/sw/bin/systemctl ${action} ${service}";
            options = [ "NOPASSWD" ];
          })
          services)
        [ "start" "stop" ];
    }];
  };
}
