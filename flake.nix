{
  description = "Rolling multi-host NixOS configuration with Noctalia, Niri, Mango, and CachyOS kernels";

  nixConfig = {
    extra-substituters = [ "https://attic.xuyh0120.win/lantian" ];
    extra-trusted-public-keys = [
      "lantian:EeAUQ+W+6r7EtwnmYjeVwx5kOGEBpjlBfPlzGlTNvHc="
    ];
  };

  inputs = {
    nixpkgs.url = "github:NixOS/nixpkgs/nixos-unstable";

    home-manager = {
      url = "github:nix-community/home-manager";
      inputs.nixpkgs.follows = "nixpkgs";
    };

    noctalia = {
      url = "github:noctalia-dev/noctalia";
      inputs.nixpkgs.follows = "nixpkgs";
    };

    noctalia-greeter = {
      url = "github:noctalia-dev/noctalia-greeter";
      inputs.nixpkgs.follows = "nixpkgs";
    };

    # Keep this input's own nixpkgs revision: the pinned overlay is built against it.
    nix-cachyos-kernel.url = "github:xddxdd/nix-cachyos-kernel/release";

    mango = {
      url = "github:mangowm/mango"; # ?ref=0.14.4
      inputs.nixpkgs.follows = "nixpkgs";
    };
  };

  outputs = inputs@{ nixpkgs, home-manager, ... }:
    let
      system = "x86_64-linux";
      pkgs = nixpkgs.legacyPackages.${system};

      desktopModules = {
        mango = ./modules/nixos/mango.nix;
        niri = ./modules/nixos/niri.nix;
      };

      hostDefinitions = {
        nyx = {
          cpuArch = "znver4";
          module = ./hosts/nyx;
          hardwareConfigPath = ./hosts/nyx/hardware-configuration.nix;
        };

        aether = {
          cpuArch = "x86-64-v3";
          module = ./hosts/aether;
          hardwareConfigPath = ./hosts/aether/hardware-configuration.nix;
          specialArgs.nvidiaPrime = {
            # Verify both IDs on the laptop with `lspci -D` before the first switch.
            intelBusId = "PCI:0:2:0";
            nvidiaBusId = "PCI:1:0:0";
          };
        };
      };

      commonModules = [
        {
          nixpkgs.overlays = [ inputs.nix-cachyos-kernel.overlays.pinned ];
        }

        ./modules/nixos/base.nix
        ./modules/nixos/storage-tuning.nix
        ./modules/nixos/desktop.nix
        ./modules/nixos/noctalia.nix
        ./modules/nixos/greeter.nix
        ./modules/flatpak

        home-manager.nixosModules.home-manager

        {
          environment.systemPackages = [
            configSyncProgram
            configUpdateProgram
            nixHelpProgram
            nixStatusProgram
            nixUpdatesProgram
            nixRefreshProgram
            nixGenerationsProgram
            nixCleanProgram
            nixOptimizeProgram
            nixRollbackProgram
            scriptUpdateProgram
            saveConfigProgram
          ];
        }
      ];

      mkHost = { hostName, desktops, defaultSession }:
        let
          host = hostDefinitions.${hostName} or (throw "Unknown host: ${hostName}");
          unknownDesktops = builtins.filter
            (desktop: !(builtins.hasAttr desktop desktopModules))
            desktops;
          hostSpecialArgs = host.specialArgs or { };
        in
        if desktops == [ ] then
          throw "Host ${hostName} must enable at least one desktop"
        else if unknownDesktops != [ ] then
          throw "Host ${hostName} contains unknown desktops: ${builtins.concatStringsSep ", " unknownDesktops}"
        else if !(builtins.elem defaultSession desktops) then
          throw "Default session ${defaultSession} is not enabled for host ${hostName}"
        else
          nixpkgs.lib.nixosSystem {
            inherit system;

            specialArgs = {
              inherit inputs desktops defaultSession hostName;
              cpuArch = host.cpuArch;
              hardwareConfigPath = host.hardwareConfigPath;
            } // hostSpecialArgs;

            modules = commonModules
              ++ [
                host.module
                {
                  home-manager = {
                    useGlobalPkgs = true;
                    useUserPackages = true;
                    backupFileExtension = "backup";
                    extraSpecialArgs = {
                      inherit inputs desktops defaultSession;
                      cpuArch = host.cpuArch;
                    } // hostSpecialArgs;
                    users.xxxxx.imports = [ ./modules/home ];
                  };
                }
              ]
              ++ map (desktop: desktopModules.${desktop}) desktops;
          };

      mkProfile = hostName: desktops: defaultSession:
        mkHost { inherit hostName desktops defaultSession; };

      configSyncProgram = pkgs.writeShellApplication {
        name = "config-sync";
        inheritPath = true;
        runtimeInputs = with pkgs; [
          coreutils diffutils findutils git gnugrep gnused jq nix python3 rsync util-linux
        ];
        text = ''
          exec ${pkgs.bash}/bin/bash \
            ${./scripts/config-sync-wrapper.sh} \
            ${./scripts/config-sync.py} \
            "$@"
        '';
        checkPhase = ''
          PYTHONPYCACHEPREFIX="$TMPDIR/pycache" \
            ${pkgs.python3}/bin/python3 -m py_compile ${./scripts/config-sync.py}
          ${pkgs.bash}/bin/bash -n ${./scripts/config-sync-wrapper.sh}
          ${pkgs.bash}/bin/bash -n "$target"
        '';
      };

      configUpdateProgram = pkgs.writeShellApplication {
        name = "config-update";
        inheritPath = true;
        runtimeInputs = with pkgs; [ coreutils git nix ];
        text = builtins.readFile ./scripts/update.sh;
        checkPhase = ''
          ${pkgs.bash}/bin/bash -n "$target"
        '';
      };

      nixHelpProgram = pkgs.writeShellApplication {
        name = "nix-help";
        inheritPath = true;
        runtimeInputs = with pkgs; [ coreutils ];
        text = builtins.readFile ./scripts/nix-help.sh;
        checkPhase = ''
          ${pkgs.bash}/bin/bash -n "$target"
        '';
      };

      nixStatusProgram = pkgs.writeShellApplication {
        name = "nix-status";
        inheritPath = true;
        runtimeInputs = with pkgs; [ coreutils findutils gawk git jq nix ];
        text = builtins.readFile ./scripts/nix-status.sh;
        checkPhase = ''
          ${pkgs.bash}/bin/bash -n "$target"
        '';
      };

      nixUpdatesProgram = pkgs.writeShellApplication {
        name = "nix-updates";
        inheritPath = true;
        runtimeInputs = with pkgs; [ coreutils findutils git jq nix ];
        text = builtins.readFile ./scripts/nix-updates.sh;
        checkPhase = ''
          ${pkgs.bash}/bin/bash -n "$target"
        '';
      };

      nixRefreshProgram = pkgs.writeShellApplication {
        name = "nix-refresh";
        inheritPath = true;
        runtimeInputs = with pkgs; [ coreutils findutils git jq nix ];
        text = builtins.readFile ./scripts/nix-refresh.sh;
        checkPhase = ''
          ${pkgs.bash}/bin/bash -n "$target"
        '';
      };

      nixGenerationsProgram = pkgs.writeShellApplication {
        name = "nix-generations";
        inheritPath = true;
        runtimeInputs = with pkgs; [ coreutils findutils gawk nix ];
        text = builtins.readFile ./scripts/nix-generations.sh;
        checkPhase = ''
          ${pkgs.bash}/bin/bash -n "$target"
        '';
      };

      nixCleanProgram = pkgs.writeShellApplication {
        name = "nix-clean";
        inheritPath = true;
        runtimeInputs = with pkgs; [ coreutils findutils nix ];
        text = builtins.readFile ./scripts/nix-clean.sh;
        checkPhase = ''
          ${pkgs.bash}/bin/bash -n "$target"
        '';
      };

      nixOptimizeProgram = pkgs.writeShellApplication {
        name = "nix-optimize";
        inheritPath = true;
        runtimeInputs = with pkgs; [ coreutils gawk nix ];
        text = builtins.readFile ./scripts/nix-optimize.sh;
        checkPhase = ''
          ${pkgs.bash}/bin/bash -n "$target"
        '';
      };

      nixRollbackProgram = pkgs.writeShellApplication {
        name = "nix-rollback";
        inheritPath = true;
        runtimeInputs = with pkgs; [ coreutils nix ];
        text = builtins.readFile ./scripts/nix-rollback.sh;
        checkPhase = ''
          ${pkgs.bash}/bin/bash -n "$target"
        '';
      };

      scriptUpdateProgram = pkgs.writeShellApplication {
        name = "script-update";
        inheritPath = true;
        runtimeInputs = with pkgs; [ coreutils diffutils findutils git jq nix python3 ];
        text = builtins.readFile ./scripts/script-update.sh;
        checkPhase = ''
          ${pkgs.bash}/bin/bash -n "$target"
        '';
      };

      saveConfigProgram = pkgs.writeShellApplication {
        name = "save-config";
        inheritPath = true;
        runtimeInputs = with pkgs; [ coreutils findutils git gnugrep rsync ];
        text = builtins.readFile ./scripts/save-config.sh;
        checkPhase = ''
          ${pkgs.bash}/bin/bash -n "$target"
        '';
      };

      installProgram = pkgs.writeShellApplication {
        name = "nixos-config-install";
        inheritPath = true;
        runtimeInputs = with pkgs; [ coreutils findutils git gnugrep gnused nix rsync ];
        text = builtins.readFile ./scripts/install.sh;
        checkPhase = ''
          ${pkgs.bash}/bin/bash -n "$target"
        '';
      };
    in
    {
      nixosConfigurations = {
        nyx = mkProfile "nyx" [ "mango" "niri" ] "mango";
        nyx-mango = mkProfile "nyx" [ "mango" ] "mango";
        nyx-niri = mkProfile "nyx" [ "niri" ] "niri";

        aether = mkProfile "aether" [ "mango" "niri" ] "mango";
        aether-mango = mkProfile "aether" [ "mango" ] "mango";
        aether-niri = mkProfile "aether" [ "niri" ] "niri";
      };

      packages.${system} = {
        install = installProgram;
        update = configUpdateProgram;
        nix-help = nixHelpProgram;
        nix-status = nixStatusProgram;
        nix-updates = nixUpdatesProgram;
        nix-refresh = nixRefreshProgram;
        nix-generations = nixGenerationsProgram;
        nix-clean = nixCleanProgram;
        nix-optimize = nixOptimizeProgram;
        nix-rollback = nixRollbackProgram;
        config-sync = configSyncProgram;
        script-update = scriptUpdateProgram;
        save-config = saveConfigProgram;
      };

      apps.${system} = {
        install = { type = "app"; program = "${installProgram}/bin/nixos-config-install"; };
        update = { type = "app"; program = "${configUpdateProgram}/bin/config-update"; };
        nix-help = { type = "app"; program = "${nixHelpProgram}/bin/nix-help"; };
        nix-status = { type = "app"; program = "${nixStatusProgram}/bin/nix-status"; };
        nix-updates = { type = "app"; program = "${nixUpdatesProgram}/bin/nix-updates"; };
        nix-refresh = { type = "app"; program = "${nixRefreshProgram}/bin/nix-refresh"; };
        nix-generations = { type = "app"; program = "${nixGenerationsProgram}/bin/nix-generations"; };
        nix-clean = { type = "app"; program = "${nixCleanProgram}/bin/nix-clean"; };
        nix-optimize = { type = "app"; program = "${nixOptimizeProgram}/bin/nix-optimize"; };
        nix-rollback = { type = "app"; program = "${nixRollbackProgram}/bin/nix-rollback"; };
        config-sync = { type = "app"; program = "${configSyncProgram}/bin/config-sync"; };
        script-update = { type = "app"; program = "${scriptUpdateProgram}/bin/script-update"; };
        save-config = { type = "app"; program = "${saveConfigProgram}/bin/save-config"; };
      };
    };
}
