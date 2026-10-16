{ config, inputs, lib, pkgs, ... }:

let
  cfg = config.my.features.agentbox;
  agentbox = pkgs.callPackage ../../pkgs/agentbox { };
  user = config.my.user;
  guestUser = "agent";
  net = {
    bridge = "agentbr";
    tap = "vm-agentbox";
    host = "10.77.0.1";
    guest = "10.77.0.2";
    prefix = 24;
  };
  blockedRanges = [
    "10.0.0.0/8"
    "100.64.0.0/10"
    "127.0.0.0/8"
    "169.254.0.0/16"
    "172.16.0.0/12"
    "192.168.0.0/16"
  ];
in
{
  imports = [ inputs.microvm.nixosModules.host ];

  options.my.features.agentbox = {
    enable = lib.mkEnableOption "isolated NixOS microVM for Claude Code and Codex";

    sshKeys = lib.mkOption {
      type = lib.types.listOf lib.types.str;
      default = [ ];
      description = "Public SSH keys allowed to log into the VM (user `${guestUser}`).";
    };

    workspace = lib.mkOption {
      type = lib.types.str;
      default = "/home/${user}/agentbox";
      defaultText = lib.literalExpression ''"/home/''${config.my.user}/agentbox"'';
      description = "Host folder shared read-write with the VM as /work. The only host path the VM can see.";
    };

    memory = lib.mkOption {
      type = lib.types.int;
      default = 8192;
      description = "VM memory in MiB.";
    };

    vcpu = lib.mkOption {
      type = lib.types.int;
      default = 6;
    };

    homeSize = lib.mkOption {
      type = lib.types.int;
      default = 40960;
      description = "Size of the persistent VM home volume in MiB.";
    };

    dns = lib.mkOption {
      type = lib.types.listOf lib.types.str;
      default = [ "1.1.1.1" "9.9.9.9" ];
    };

    extraPackages = lib.mkOption {
      type = lib.types.listOf lib.types.package;
      default = [ ];
      description = "Additional packages inside the VM.";
    };
  };

  config = lib.mkMerge [
    { microvm.host.enable = cfg.enable; }

    (lib.mkIf cfg.enable {
      assertions = [{
        assertion = cfg.sshKeys != [ ];
        message = "my.features.agentbox.sshKeys must contain at least one public key.";
      }];

      environment.systemPackages = [ agentbox ];

      environment.etc."agentbox.conf".text = ''
        VM=agentbox
        ADDR=${net.guest}
        WORKSPACE=${lib.escapeShellArg cfg.workspace}
        VM_USER=${guestUser}
      '';

      # Lets `ssh agentbox` work from any tool, e.g. VSCodium Remote-SSH.
      programs.ssh.extraConfig = ''
        Host agentbox
          HostName ${net.guest}
          User ${guestUser}
          StrictHostKeyChecking accept-new
          UserKnownHostsFile ~/.ssh/known_hosts_agentbox
      '';

      # The user may start and stop the VM without a password.
      security.sudo.extraRules = [{
        users = [ user ];
        commands = map
          (c: { command = "/run/current-system/sw/bin/systemctl ${c} microvm@agentbox.service"; options = [ "NOPASSWD" ]; })
          [ "start" "stop" "restart" ];
      }];

      systemd.tmpfiles.rules = [ "d ${cfg.workspace} 0755 ${user} users -" ];

      # --- host-enforced network policy ----------------------------------
      # The VM sits on a private bridge, NATs to the internet and can reach
      # neither the host's services nor the LAN, whatever happens inside it.
      systemd.network = {
        enable = true;
        # NetworkManager stays in charge of real links; the bridge never has
        # carrier without a running VM, so do not wait for it at boot.
        wait-online.enable = false;
        netdevs."20-${net.bridge}".netdevConfig = {
          Kind = "bridge";
          Name = net.bridge;
        };
        networks."20-${net.bridge}" = {
          matchConfig.Name = net.bridge;
          addresses = [{ Address = "${net.host}/${toString net.prefix}"; }];
          networkConfig.ConfigureWithoutCarrier = true;
        };
        networks."21-${net.tap}" = {
          matchConfig.Name = net.tap;
          networkConfig.Bridge = net.bridge;
        };
      };

      networking.networkmanager.unmanaged = [ net.bridge net.tap ];
      networking.nat = {
        enable = true;
        internalInterfaces = [ net.bridge ];
      };

      networking.firewall = lib.mkMerge [
        (lib.mkIf config.networking.nftables.enable {
          extraForwardRules = ''
            iifname "${net.bridge}" ip daddr { ${lib.concatStringsSep ", " blockedRanges} } drop
          '';
          extraInputRules = ''
            iifname "${net.bridge}" drop
          '';
        })
        (lib.mkIf (!config.networking.nftables.enable) {
          extraCommands = ''
            ${lib.concatMapStringsSep "\n"
              (r: "iptables -I FORWARD -i ${net.bridge} -d ${r} -j DROP")
              blockedRanges}
            iptables -I INPUT -i ${net.bridge} -j DROP
          '';
          extraStopCommands = ''
            ${lib.concatMapStringsSep "\n"
              (r: "iptables -D FORWARD -i ${net.bridge} -d ${r} -j DROP || true")
              blockedRanges}
            iptables -D INPUT -i ${net.bridge} -j DROP || true
          '';
        })
      ];

      # --- the VM --------------------------------------------------------
      microvm.vms.agentbox = {
        autostart = false;
        config = { pkgs, ... }: {
          system.stateVersion = "25.11";
          networking.hostName = "agentbox";

          microvm = {
            hypervisor = "qemu";
            mem = cfg.memory;
            vcpu = cfg.vcpu;

            interfaces = [{
              type = "tap";
              id = net.tap;
              mac = "02:00:00:a6:e1:01";
            }];

            shares = [
              {
                proto = "virtiofs";
                tag = "ro-store";
                source = "/nix/store";
                mountPoint = "/nix/.ro-store";
              }
              {
                proto = "virtiofs";
                tag = "work";
                source = cfg.workspace;
                mountPoint = "/work";
              }
            ];

            volumes = [
              { image = "home.img"; mountPoint = "/home/${guestUser}"; size = cfg.homeSize; }
              { image = "nix-rw.img"; mountPoint = "/nix/.rw-store"; size = 8192; }
            ];
            writableStoreOverlay = "/nix/.rw-store";
          };

          networking.useNetworkd = true;
          networking.useDHCP = false;
          systemd.network.networks."20-lan" = {
            matchConfig.Type = "ether";
            address = [ "${net.guest}/${toString net.prefix}" ];
            gateway = [ net.host ];
            dns = cfg.dns;
          };
          networking.nameservers = cfg.dns;

          users.users.${guestUser} = {
            isNormalUser = true;
            uid = 1000;
            extraGroups = [ "wheel" ];
            openssh.authorizedKeys.keys = cfg.sshKeys;
          };
          # Full control inside the VM is the point of the box.
          security.sudo.wheelNeedsPassword = false;

          services.openssh = {
            enable = true;
            settings = {
              PasswordAuthentication = false;
              KbdInteractiveAuthentication = false;
              PermitRootLogin = "no";
            };
          };
          networking.firewall.allowedTCPPorts = [ 22 ];

          # Lets the downloaded VSCodium server run on NixOS.
          programs.nix-ld.enable = true;

          nix.settings.experimental-features = [ "nix-command" "flakes" ];

          environment.systemPackages = with pkgs; [
            claude-code
            codex
            git
            gh
            nodejs
            python3
            ripgrep
            fd
            jq
            gnumake
            gcc
            curl
            tmux
            neovim
            unzip
          ] ++ cfg.extraPackages;

          environment.shellAliases = {
            yolo-claude = "claude --dangerously-skip-permissions";
            yolo-codex = "codex --dangerously-bypass-approvals-and-sandbox";
          };
        };
      };
    })
  ];
}
