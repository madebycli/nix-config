{
  description = "Rolling multi-host NixOS configuration with Mango, Niri, Hyprland, Noctalia, Caelestia Shell, and CachyOS kernels";

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

    caelestia-shell = {
      url = "github:caelestia-dots/shell";
      inputs.nixpkgs.follows = "nixpkgs";
    };

    # Keep this input's own nixpkgs revision: the pinned overlay is built against it.
    nix-cachyos-kernel.url = "github:xddxdd/nix-cachyos-kernel/release";

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
            enable = true;
            sshKeys = [ "ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIDUMMYDUMMYDUMMYDUMMYDUMMYDUMMYDUMMYDUMMYDUMM ci" ];
          };
          sandbox.apps.example = {
            command = [ "echo" "hello" ];
            net = "inet";
          };
        };
      };

      mkHost = hostName: extraModules:
        lib.nixosSystem {
          inherit system;
          specialArgs = { inherit inputs hostName; };
          modules = [ ./modules ./hosts/${hostName} ] ++ extraModules;
        };

      tools = import ./pkgs/tools.nix { inherit pkgs; };
      gbox = pkgs.callPackage ./pkgs/gbox { };
      dots = pkgs.callPackage ./pkgs/dots { };
      agentbox = pkgs.callPackage ./pkgs/agentbox { };
    in
    {
      nixosConfigurations =
        lib.genAttrs hosts (host: mkHost host [ ])
        // lib.genAttrs (map (h: "ci-${h}") hosts)
          (name: mkHost (lib.removePrefix "ci-" name) [ ciStub ])
        // lib.genAttrs (map (h: "ci-${h}-full") hosts)
          (name: mkHost (lib.removeSuffix "-full" (lib.removePrefix "ci-" name)) [ ciStub ciFull ]);

      packages.${system} = tools // {
        inherit gbox dots agentbox;
        install = tools.nixos-config-install;
        update = tools.config-update;
      };

      apps.${system} =
        lib.mapAttrs
          (name: pkg: { type = "app"; program = lib.getExe pkg; })
          (tools // { inherit gbox dots agentbox; })
        // {
          install = { type = "app"; program = lib.getExe tools.nixos-config-install; };
          update = { type = "app"; program = lib.getExe tools.config-update; };
        };

      formatter.${system} = pkgs.nixpkgs-fmt;
    };
}
