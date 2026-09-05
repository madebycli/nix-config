let
  repoRoot = ../.;
  flake = builtins.getFlake ("path:" + toString repoRoot);
  nixpkgs = flake.inputs.nixpkgs;
  requestedTheme =
    let
      value = builtins.getEnv "PLMF_TEST_THEME";
    in
    if value == "" then "minimal" else value;
  selectorValue = builtins.getEnv "PLMF_TEST_SELECTOR";
  expectedTheme =
    if builtins.elem selectorValue [ "minimal" "zoot" ] then
      selectorValue
    else
      requestedTheme;

  testSystem = nixpkgs.lib.nixosSystem {
    system = "x86_64-linux";

    modules = [
      ../modules/nixos/boot-splash.nix
      flake.inputs.noctalia-greeter.nixosModules.default

      ({ config, lib, modulesPath, pkgs, ... }:
        {
          imports = [ (modulesPath + "/virtualisation/qemu-vm.nix") ];

          networking.hostName = "plmf-boot-splash-vm";

          boot = {
            loader = {
              systemd-boot = {
                enable = true;
                extraFiles = lib.optionalAttrs (selectorValue != "") {
                  "EFI/PLMF/theme" = pkgs.writeText "plmf-test-theme-selector" "${selectorValue}\n";
                };
              };
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
              TimeoutStartSec = "8s";
            };
            script = ''
              set -eu

              ${config.boot.plymouth.package}/bin/plymouth --ping
              printf 'active\n' > /run/plmf/plymouth-active

              ${config.boot.initrd.systemd.package}/bin/systemd-ask-password \
                --timeout=5 \
                "PLMF VM password phase" >/dev/null || true

              ${config.boot.plymouth.package}/bin/plymouth --ping
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

          # The qemu-vm module exposes /tmp/xchg as a host/guest exchange directory.
          # CI waits for this marker, so a green smoke test proves that the real VM
          # reached stage 2, retained the initrd theme decision, and started Noctalia.
          systemd.services.plmf-ci-ready = {
            description = "Report successful PLMF boot smoke test";
            wantedBy = [ "multi-user.target" ];
            wants = [ "greetd.service" ];
            after = [ "greetd.service" ];
            path = with pkgs; [ coreutils procps systemd ];
            serviceConfig.Type = "oneshot";
            script = ''
              set -eu

              expected=${lib.escapeShellArg expectedTheme}
              if [ ! -r /run/plmf/effective-theme ]; then
                echo "PLMF effective-theme marker did not survive switch-root" >&2
                exit 1
              fi
              if [ ! -r /run/plmf/plymouth-active ]; then
                echo "Plymouth was not confirmed active in initrd" >&2
                exit 1
              fi

              actual=$(cat /run/plmf/effective-theme)
              if [ "$actual" != "$expected" ]; then
                echo "PLMF theme mismatch: expected=$expected actual=$actual" >&2
                exit 1
              fi

              systemctl is-active --quiet greetd.service

              attempts=0
              while ! pgrep -f 'noctalia-greeter' >/dev/null 2>&1; do
                attempts=$((attempts + 1))
                if [ "$attempts" -ge 30 ]; then
                  echo "Noctalia Greeter did not start" >&2
                  systemctl status greetd.service --no-pager >&2 || true
                  exit 1
                fi
                sleep 1
              done

              mkdir -p /tmp/xchg
              {
                printf 'expected=%s\n' "$expected"
                printf 'actual=%s\n' "$actual"
                printf 'plymouth=active\n'
                printf 'greetd=active\n'
                printf 'noctalia=active\n'
              } > /tmp/xchg/plmf-ready
            '';
          };

          system.stateVersion = "25.11";
        })
    ];
  };
in
testSystem.config.system.build.vm
