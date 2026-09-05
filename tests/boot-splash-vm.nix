let
  repoRoot = ../.;
  flake = builtins.getFlake ("path:" + toString repoRoot);
  nixpkgs = flake.inputs.nixpkgs;
  requestedTheme =
    let
      value = builtins.getEnv "PLMF_TEST_THEME";
    in
    if value == "" then "minimal" else value;

  testSystem = nixpkgs.lib.nixosSystem {
    system = "x86_64-linux";

    modules = [
      ../modules/nixos/boot-splash.nix
      flake.inputs.noctalia-greeter.nixosModules.default

      ({ config, modulesPath, ... }:
        {
          imports = [ (modulesPath + "/virtualisation/qemu-vm.nix") ];

          networking.hostName = "plmf-boot-splash-vm";

          boot = {
            loader = {
              systemd-boot.enable = true;
              efi.canTouchEfiVariables = true;
            };

            kernelParams = [
              "quiet"
              "loglevel=3"
              "rd.systemd.show_status=false"
              "systemd.show_status=false"
            ];
            consoleLogLevel = 0;
          };

          plmf.bootSplash = {
            enable = true;
            defaultTheme = requestedTheme;
          };

          virtualisation = {
            useBootLoader = true;
            useEFIBoot = true;
            memorySize = 2048;
            cores = 2;
            graphics = true;
            diskSize = 8192;
          };

          # Exercise the normal systemd/Plymouth ask-password path in the initrd.
          # The entered value is intentionally discarded and never parsed or logged.
          boot.initrd.systemd.services.plmf-test-password = {
            description = "PLMF Plymouth ask-password test";
            wantedBy = [ "initrd.target" ];
            after = [ "plymouth-start.service" ];
            before = [ "initrd-switch-root.target" ];
            serviceConfig = {
              Type = "oneshot";
              TimeoutStartSec = "25s";
            };
            script = ''
              ${config.boot.initrd.systemd.package}/bin/systemd-ask-password \
                --timeout=20 \
                "PLMF VM password phase" >/dev/null || true
            '';
          };

          programs.noctalia-greeter = {
            enable = true;
            settings = {
              keyboard.layout = "de";
              user.default = "plmf";
            };
          };

          users.users.plmf = {
            isNormalUser = true;
            initialPassword = "plmf";
            extraGroups = [ "wheel" ];
          };
          security.sudo.wheelNeedsPassword = false;

          system.stateVersion = "25.11";
        })
    ];
  };
in
testSystem.config.system.build.vm
