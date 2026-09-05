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

            # Pull cryptsetup.target into the initrd even though the CI VM uses
            # an unencrypted root. The synthetic password service below becomes
            # part of that target and models the hardware LUKS interaction.
            initrd.luks.forceLuksSupportInInitrd = true;
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

          # Model the real machine's password phase as work that must complete
          # before cryptsetup.target. Plymouth must stay inactive for the whole
          # prompt, exactly like on nyx.
          boot.initrd.systemd.services.plmf-test-password-before-plymouth = {
            description = "PLMF synthetic LUKS password phase";
            wantedBy = [ "cryptsetup.target" ];
            after = [ "systemd-udev-trigger.service" ];
            before = [
              "cryptsetup.target"
              "plymouth-start.service"
            ];
            serviceConfig = {
              Type = "oneshot";
              TimeoutStartSec = "8s";
            };
            script = ''
              set -eu

              mkdir -p /run/plmf

              if ${config.boot.plymouth.package}/bin/plymouth --ping >/dev/null 2>&1; then
                echo "Plymouth became active before the password phase" >&2
                exit 1
              fi
              printf 'inactive\n' > /run/plmf/plymouth-before-unlock

              ${config.boot.initrd.systemd.package}/bin/systemd-ask-password \
                --timeout=2 \
                "PLMF VM synthetic LUKS password phase" >/dev/null || true

              if ${config.boot.plymouth.package}/bin/plymouth --ping >/dev/null 2>&1; then
                echo "Plymouth became active during the password phase" >&2
                exit 1
              fi
              printf 'complete\n' > /run/plmf/unlock-phase
            '';
          };

          # Plymouth should start as soon as cryptsetup.target has completed and
          # before root filesystem work finishes, not at the later switch-root
          # boundary.
          boot.initrd.systemd.services.plmf-test-plymouth-after-unlock = {
            description = "Confirm PLMF Plymouth starts after unlock";
            wantedBy = [ "initrd-root-device.target" ];
            after = [
              "cryptsetup.target"
              "plmf-test-password-before-plymouth.service"
              "plymouth-start.service"
            ];
            before = [ "initrd-root-fs.target" ];
            serviceConfig = {
              Type = "oneshot";
              TimeoutStartSec = "8s";
            };
            script = ''
              set -eu

              test "$(cat /run/plmf/unlock-phase)" = complete
              ${config.boot.plymouth.package}/bin/plymouth --ping
              printf 'active-after-unlock\n' > /run/plmf/plymouth-active
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

          # CI reaches this only after greetd has run the PLMF handoff service.
          # We verify that Plymouth was active after unlock, that the handoff used
          # --retain-splash, and that Plymouth has released DRM by the time the
          # Noctalia process exists.
          systemd.services.plmf-ci-ready = {
            description = "Report successful PLMF boot smoke test";
            wantedBy = [ "multi-user.target" ];
            wants = [ "greetd.service" ];
            after = [ "greetd.service" ];
            path = with pkgs; [ coreutils procps systemd config.boot.plymouth.package ];
            serviceConfig.Type = "oneshot";
            script = ''
              set -eu

              expected=${lib.escapeShellArg expectedTheme}
              if [ ! -r /run/plmf/effective-theme ]; then
                echo "PLMF effective-theme marker did not survive switch-root" >&2
                exit 1
              fi
              if [ ! -r /run/plmf/plymouth-before-unlock ]; then
                echo "Pre-Plymouth password phase marker is missing" >&2
                exit 1
              fi
              if [ "$(cat /run/plmf/plymouth-before-unlock)" != "inactive" ]; then
                echo "Plymouth was unexpectedly active before unlock" >&2
                exit 1
              fi
              if [ ! -r /run/plmf/plymouth-active ]; then
                echo "Plymouth was not confirmed active after unlock" >&2
                exit 1
              fi
              if [ "$(cat /run/plmf/plymouth-active)" != "active-after-unlock" ]; then
                echo "Unexpected Plymouth post-unlock marker" >&2
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

              if [ ! -r /run/plmf/greeter-handoff ]; then
                echo "PLMF greeter handoff marker is missing" >&2
                exit 1
              fi
              if [ "$(cat /run/plmf/greeter-handoff)" != "retain-splash" ]; then
                echo "PLMF greeter handoff did not retain the last splash frame" >&2
                exit 1
              fi
              if plymouth --ping >/dev/null 2>&1; then
                echo "Plymouth is still active after greetd handoff" >&2
                exit 1
              fi

              mkdir -p /tmp/xchg
              {
                printf 'expected=%s\n' "$expected"
                printf 'actual=%s\n' "$actual"
                printf 'pre-plymouth=inactive\n'
                printf 'unlock=complete\n'
                printf 'plymouth=active-after-unlock\n'
                printf 'handoff=retain-splash\n'
                printf 'plymouth-after-handoff=inactive\n'
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
