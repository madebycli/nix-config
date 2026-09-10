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
              # The UEFI smoke test has no interactive boot-menu input. Boot the
              # generated entry after a bounded one-second selection window so
              # the test measures the initrd and greeter handoff instead of
              # waiting indefinitely at systemd-boot. This is CI-only.
              # This setting exists only in the CI VM fixture, not on Aether.
              timeout = 1;
              systemd-boot = {
                enable = true;
              };
              efi.canTouchEfiVariables = true;
            };

            kernelParams = [
              # Keep an explicit serial console for CI diagnostics while
              # retaining the normal quiet/status behavior of the fixture.
              "console=ttyS0,115200n8"
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
            # The VM has no real encrypted volume, so cryptsetup.target is not
            # pulled in by a generated cryptsetup job. Pull the target in from
            # the smoke chain so this service still models the real unlock
            # boundary instead of racing initrd-root-device.target.
            wantedBy = [
              "sysinit.target"
              "cryptsetup.target"
              "initrd-root-device.target"
            ];
            after = [ "systemd-udev-trigger.service" ];
            before = [
              "sysinit.target"
              "cryptsetup.target"
              "initrd-root-device.target"
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

          # Seed the selector after the ESP is available instead of using
          # systemd-boot.extraFiles. The latter changes the generated UEFI
          # fixture in a way that can leave OVMF before the boot manager has
          # transferred control to the kernel. This service models the same
          # persisted selector file while keeping the bootloader fixture
          # identical for all theme cases.
          boot.initrd.systemd.services.plmf-test-selector = lib.mkIf (selectorValue != "") {
            description = "Seed the PLMF selector on the synthetic ESP";
            wantedBy = [ "sysinit.target" ];
            after = [ "systemd-udev-trigger.service" ];
            before = [ "plmf-select-theme.service" "plymouth-start.service" ];
            path = with pkgs; [ coreutils util-linux ];
            serviceConfig = {
              Type = "oneshot";
              TimeoutStartSec = "8s";
            };
            script = ''
              set -eu

              esp_mount=/run/plmf-test-esp
              mkdir -p "$esp_mount"
              timeout 3s mount \
                -t vfat \
                -o rw,nosuid,nodev,noexec \
                /dev/disk/by-label/ESP \
                "$esp_mount"
              mkdir -p "$esp_mount/EFI/PLMF"
              printf '%s\n' ${lib.escapeShellArg selectorValue} > "$esp_mount/EFI/PLMF/theme"
              timeout 2s umount "$esp_mount"
            '';
          };

          # Plymouth should start as soon as cryptsetup.target has completed and
          # before root filesystem work finishes, not at the later switch-root
          # boundary.
          boot.initrd.systemd.services.plmf-test-plymouth-after-unlock = {
            description = "Confirm PLMF Plymouth starts after unlock";
            wantedBy = [ "initrd-root-device.target" ];
            wants = [
              "cryptsetup.target"
              "plmf-select-theme.service"
              "plymouth-start.service"
            ];
            after = [
              "cryptsetup.target"
              "plmf-test-password-before-plymouth.service"
              "plmf-select-theme.service"
              "plymouth-start.service"
            ];
            before = [ "initrd-root-fs.target" ];
            serviceConfig = {
              Type = "oneshot";
              TimeoutStartSec = "8s";
            };
            script = ''
              set -u

              mkdir -p /run/plmf
              fail() {
                printf '%s\n' "$1" > /run/plmf/test-failure
                exit 1
              }

              if [ ! -r /run/plmf/unlock-phase ] || \
                [ "$(cat /run/plmf/unlock-phase)" != complete ]; then
                fail unlock-marker-missing
              fi
              if ! ${config.boot.plymouth.package}/bin/plymouth --ping; then
                fail plymouth-not-active
              fi
              printf 'active-after-unlock\n' > /run/plmf/plymouth-active
            '';
          };

          # Initrd /run is intentionally not the stage-2 /run. Persist the
          # initrd observations on the mounted root so the stage-2 assertion
          # can validate the unlock-to-Plymouth ordering after switch-root.
          boot.initrd.systemd.services.plmf-test-persist-markers = {
            description = "Persist PLMF initrd smoke markers";
            wantedBy = [ "initrd-switch-root.target" ];
            after = [
              "initrd-fs.target"
              "initrd-root-fs.target"
              "plmf-test-plymouth-after-unlock.service"
            ];
            before = [ "initrd-switch-root.target" "initrd-switch-root.service" ];
            path = with pkgs; [ coreutils ];
            unitConfig.DefaultDependencies = false;
            serviceConfig = {
              Type = "oneshot";
              TimeoutStartSec = "8s";
            };
            script = ''
              set -eu

              marker_dir=/sysroot/var/lib/plmf-test
              mkdir -p "$marker_dir"
              for marker in \
                effective-theme \
                plymouth-before-unlock \
                unlock-phase \
                plymouth-active; do
                if [ -r "/run/plmf/$marker" ]; then
                  cp "/run/plmf/$marker" "$marker_dir/$marker"
                fi
              done
              if [ -r /run/plmf/test-failure ]; then
                cp /run/plmf/test-failure "$marker_dir/test-failure"
              fi
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

              marker_dir=/var/lib/plmf-test

              fail() {
                reason="$1"
                echo "PLMF CI failure: $reason" >&2
                mkdir -p /tmp/xchg
                printf 'failure=%s\n' "$reason" > /tmp/xchg/plmf-failure
                printf 'effective-theme=' >&2
                cat "$marker_dir/effective-theme" >&2 2>/dev/null || true
                printf 'initrd-test=' >&2
                cat "$marker_dir/test-failure" >&2 2>/dev/null || true
                printf 'greeter-handoff=' >&2
                cat /run/plmf/greeter-handoff >&2 2>/dev/null || true
                pgrep -af 'noctalia-greeter' >&2 || true
                systemctl --no-pager status greetd.service >&2 || true
                exit 1
              }

              expected=${lib.escapeShellArg expectedTheme}
              if [ -r "$marker_dir/test-failure" ]; then
                fail initrd-test-failed
              fi
              if [ ! -r "$marker_dir/effective-theme" ]; then
                fail effective-theme-marker-missing
              fi
              if [ ! -r "$marker_dir/plymouth-before-unlock" ]; then
                fail pre-plymouth-marker-missing
              fi
              if [ "$(cat "$marker_dir/plymouth-before-unlock")" != "inactive" ]; then
                fail plymouth-active-before-unlock
              fi
              if [ ! -r "$marker_dir/plymouth-active" ]; then
                fail plymouth-active-marker-missing
              fi
              if [ "$(cat "$marker_dir/plymouth-active")" != "active-after-unlock" ]; then
                fail plymouth-active-marker-invalid
              fi

              actual=$(cat "$marker_dir/effective-theme")
              if [ "$actual" != "$expected" ]; then
                fail theme-mismatch
              fi

              systemctl is-active --quiet greetd.service || fail greetd-inactive

              attempts=0
              while ! pgrep -f 'noctalia-greeter' >/dev/null 2>&1; do
                attempts=$((attempts + 1))
                if [ "$attempts" -ge 30 ]; then
                  fail noctalia-greeter-not-started
                fi
                sleep 1
              done

              if [ ! -r /run/plmf/greeter-handoff ]; then
                fail greeter-handoff-marker-missing
              fi
              if [ "$(cat /run/plmf/greeter-handoff)" != "retain-splash" ]; then
                fail greeter-handoff-not-retained
              fi
              if plymouth --ping >/dev/null 2>&1; then
                fail plymouth-still-active
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
