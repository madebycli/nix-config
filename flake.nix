{
  description = "Rolling multi-host NixOS configuration with Mango, Niri, Hyprland, Noctalia, Caelestia Shell, and CachyOS kernels";

  inputs = {
    nixpkgs.url = "github:NixOS/nixpkgs/nixos-unstable";

    home-manager = {
      url = "github:nix-community/home-manager";
      inputs.nixpkgs.follows = "nixpkgs";
    };

    # Former upstream shell Flake, intentionally disabled.
    # noctalia = {
    #   url = "github:noctalia-dev/noctalia";
    #   inputs.nixpkgs.follows = "nixpkgs";
    # };
    # Active Noctalia + noctalia-greeter packages come from the existing
    # nixpkgs (nixos-unstable) input; see modules/desktop/*.nix.
    # nx update desktop (and nx update noctalia) refreshes this nixpkgs input.

    caelestia-shell = {
      url = "github:caelestia-dots/shell";
      inputs.nixpkgs.follows = "nixpkgs";
    };

    # Track current sources; release waits for upstream binary-cache builds.
    # Keep this input's own nixpkgs revision for matching patches and modules.
    nix-cachyos-kernel.url = "github:xddxdd/nix-cachyos-kernel/master";

    # Declarative microVMs; hosts the isolated agent box (my.features.agentbox).
    microvm = {
      url = "github:microvm-nix/microvm.nix";
      inputs.nixpkgs.follows = "nixpkgs";
      # Only used by microvm's cloud-hypervisor graphics overlay, which we never evaluate.
      inputs.spectrum.follows = "nixpkgs";
    };

    mango = {
      url = "github:mangowm/mango"; # ?ref=0.14.4
      inputs.nixpkgs.follows = "nixpkgs";
    };
  };

  outputs = inputs@{ nixpkgs, ... }:
    let
      system = "x86_64-linux";
      pkgs = nixpkgs.legacyPackages.${system};
      lib = nixpkgs.lib;

      hosts = [ "nyx" "aether" ];

      # Evaluation-only stand-in for the machine-specific root file system.
      # Used by `nix flake check` and CI, never installed.
      ciStub = {
        fileSystems."/" = { device = "none"; fsType = "tmpfs"; };
        fileSystems."/boot" = { device = "none"; fsType = "vfat"; };
        boot.loader.grub.enable = false;
      };

      # Switches every optional feature on so `nix flake check` covers them all.
      ciFull = {
        my.features = {
          agentbox = {
            enable = lib.mkForce true;
            sshKeys = [ "ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIDUMMYDUMMYDUMMYDUMMYDUMMYDUMMYDUMMYDUMMYDUMM ci" ];
          };
          virtualisation.enable = lib.mkForce true;
          ai.enable = lib.mkForce true;
          local-ai.enable = lib.mkForce true;
        };
      };

      mkHost = hostName: extraModules:
        lib.nixosSystem {
          inherit system;
          specialArgs = { inherit inputs hostName; };
          modules = [ ./modules ./hosts/${hostName} ] ++ extraModules;
        };

      tools = import ./pkgs/tools.nix { inherit pkgs; };
      dots = pkgs.callPackage ./pkgs/dots { };
      agentbox = pkgs.callPackage ./pkgs/agentbox { };
      nixctl = pkgs.callPackage ./pkgs/nixctl { };
      nx = pkgs.callPackage ./pkgs/nx { };
      aiboxPackages = import ./pkgs/aibox { inherit pkgs lib; };
      inherit (aiboxPackages) aibox;
    in
    {
      nixosConfigurations =
        lib.genAttrs hosts (host: mkHost host [ ])
        // lib.genAttrs (map (h: "ci-${h}") hosts)
          (name: mkHost (lib.removePrefix "ci-" name) [ ciStub ])
        // lib.genAttrs (map (h: "ci-${h}-full") hosts)
          (name: mkHost (lib.removeSuffix "-full" (lib.removePrefix "ci-" name)) [ ciStub ciFull ]);

      packages.${system} = tools // {
        inherit dots agentbox nixctl nx aibox;
        aibox-agent-image = aiboxPackages.agentImage;
        install = tools.nixos-config-install;
      };

      apps.${system} =
        lib.mapAttrs
          (name: pkg: { type = "app"; program = lib.getExe pkg; })
          (tools // { inherit dots agentbox nixctl nx aibox; })
        // {
          install = { type = "app"; program = lib.getExe tools.nixos-config-install; };
        };

      # Enter with `nix develop .#<name>` or via direnv (`echo "use flake <repo>#ai-rocm" > .envrc`).
      devShells.${system} =
        let
          pkgs = import nixpkgs { inherit system; config.allowUnfree = true; };
          aiShell = llama: pkgs.mkShell {
            packages = [ llama pkgs.uv pkgs.python3 pkgs.python3Packages.huggingface-hub ];
            shellHook = ''
              echo "AI shell: llama.cpp, uv, python, huggingface-cli"
            '';
          };
        in
        {
          default = pkgs.mkShell {
            packages = with pkgs; [ nixpkgs-fmt deadnix statix shellcheck gitleaks git ];
          };
          ai-cpu = aiShell pkgs.llama-cpp;
          ai-rocm = aiShell (pkgs.llama-cpp.override { rocmSupport = true; });
          ai-cuda = aiShell (pkgs.llama-cpp.override { cudaSupport = true; });
        };

      formatter.${system} = pkgs.nixpkgs-fmt;
    };
}
