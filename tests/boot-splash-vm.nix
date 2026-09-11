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
              # systemd stage 1 mounts the synthetic root read-only unless
              # this is explicit. The fixture-only marker persistence service
              # needs a writable test root; production hosts are unchanged.
              "rw"
              "quiet"
              "loglevel=3"
              "rd.systemd.show_status=false"
              "systemd.show_status=false"
              # Keep a CI-only Plymouth trace on the synthetic root so a
              # theme-specific daemon failure is distinguishable from a
              # systemd ordering failure. Production hosts do not inherit
              # this diagnostic parameter.
              "plymouth.debug=file:/run/plmf/plymouth-debug.log"
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
            unitConfig.DefaultDependencies = false;
            serviceConfig = {
              Type = "oneshot";
              TimeoutStartSec = "8s";
            };
            script = ''
              set -eu

              mkdir -p /run/plmf
              printf 'started\n' > /run/plmf/password-phase

              if timeout 1s ${config.boot.plymouth.package}/bin/plymouth --ping >/dev/null 2>&1; then
                echo "Plymouth became active before the password phase" >&2
                exit 1
              fi
              printf 'inactive\n' > /run/plmf/plymouth-before-unlock

              # CI cannot provide an interactive password. Query only password
              # agents so this models the prompt boundary without blocking the
              # UEFI smoke test on a synthetic console.
              ${config.boot.initrd.systemd.package}/bin/systemd-ask-password \
                --no-tty \
                --timeout=2 \
                "PLMF VM synthetic LUKS password phase" >/dev/null || true

              if timeout 1s ${config.boot.plymouth.package}/bin/plymouth --ping >/dev/null 2>&1; then
                echo "Plymouth became active during the password phase" >&2
                exit 1
              fi
              printf 'complete\n' > /run/plmf/unlock-phase
            '';
          };

          # The production Plymouth unit is also pulled in directly by
          # initrd-root-device.target. Add the synthetic password phase to that
          # unit's own ordering so it cannot race the cryptsetup-target edge.
          boot.initrd.systemd.services.plymouth-start = {
            requires = [ "plmf-test-password-before-plymouth.service" ];
            wants = [ "plmf-test-password-before-plymouth.service" ];
            after = [ "plmf-test-password-before-plymouth.service" ];
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
            requires = [ "dev-disk-by\\x2dlabel-ESP.device" ];
            after = [
              "systemd-udev-trigger.service"
              "dev-disk-by\\x2dlabel-ESP.device"
            ];
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

          # Pull the fixture-only selector into the real theme-selection chain.
          # A wantedBy=sysinit link alone does not guarantee that it has finished
          # before the production selector service is scheduled.
          boot.initrd.systemd.services.plmf-select-theme = lib.mkIf (selectorValue != "") {
            requires = [ "plmf-test-selector.service" ];
            wants = [ "plmf-test-selector.service" ];
            after = [ "plmf-test-selector.service" ];
          };

          # Plymouth should start as soon as cryptsetup.target has completed and
          # before root filesystem work finishes, not at the later switch-root
          # boundary.
          boot.initrd.systemd.services.plmf-test-plymouth-after-unlock = {
            description = "Confirm PLMF Plymouth starts after unlock";
            wantedBy = [ "initrd-root-device.target" ];
            requires = [
              "cryptsetup.target"
              "plmf-ask-password-console.service"
              "plmf-test-password-before-plymouth.service"
              "plmf-select-theme.service"
              "plymouth-start.service"
            ];
            wants = [
              "cryptsetup.target"
              "plmf-ask-password-console.service"
              "plmf-test-password-before-plymouth.service"
              "plmf-select-theme.service"
              "plymouth-start.service"
            ];
            after = [
              "cryptsetup.target"
              "plmf-ask-password-console.service"
              "plmf-test-password-before-plymouth.service"
              "plymouth-start.service"
            ];
            before = [ "initrd-root-fs.target" ];
            path = with pkgs; [ coreutils procps systemd config.boot.plymouth.package ];
            serviceConfig = {
              Type = "oneshot";
              TimeoutStartSec = "12s";
            };
            script = ''
              set -u

              mkdir -p /run/plmf
              fail() {
                printf '%s\n' "$1" > /run/plmf/test-failure
                {
                  printf 'password-unit=\n'
                  timeout 2s systemctl show \
                    --property=LoadState,ActiveState,SubState,Result,ExecMainCode,ExecMainStatus \
                    plmf-test-password-before-plymouth.service 2>&1 || true
                  printf 'password-agent-unit=\n'
                  timeout 2s systemctl show \
                    --property=LoadState,ActiveState,SubState,Result,ExecMainCode,ExecMainStatus \
                    plmf-ask-password-console.service 2>&1 || true
                  printf 'selector-unit=\n'
                  timeout 2s systemctl show \
                    --property=LoadState,ActiveState,SubState,Result,ExecMainCode,ExecMainStatus \
                    plmf-select-theme.service 2>&1 || true
                  printf 'plymouth-unit=\n'
                  timeout 2s systemctl show \
                    --property=LoadState,ActiveState,SubState,Result,ExecMainCode,ExecMainStatus \
                    plymouth-start.service 2>&1 || true
                } >> /run/plmf/test-failure
                exit 1
              }

              if [ ! -r /run/plmf/unlock-phase ] || \
                [ "$(cat /run/plmf/unlock-phase)" != complete ]; then
                fail unlock-marker-missing
              fi
              if ! systemctl is-active --quiet plmf-ask-password-console.service; then
                fail password-agent-inactive
              fi
              plymouth_ready=0
              for attempt in 1 2 3 4 5; do
                if timeout 1s ${config.boot.plymouth.package}/bin/plymouth --ping; then
                  plymouth_ready=1
                  break
                fi
              done
              if [ "$plymouth_ready" -ne 1 ]; then
                {
                  printf 'reason=plymouth-not-active-or-timeout\n'
                  printf 'ping=failed-or-timeout\n'
                  printf 'pid='; cat /run/plymouth/pid 2>/dev/null || true
                  printf 'processes=\n'
                  pgrep -af plymouth 2>/dev/null || true
                  printf 'socket-dir=\n'
                  ls -la /run/plymouth 2>/dev/null || true
                  printf 'config=\n'
                  cat /etc/plymouth/plymouthd.conf 2>/dev/null || true
                  printf 'run-debug=\n'
                  cat /run/plmf/plymouth-debug.log 2>/dev/null || true
                  printf 'var-debug=\n'
                  cat /var/log/plymouth-debug.log 2>/dev/null || true
                  printf 'tmp-debug=\n'
                  cat /tmp/plymouth-debug.log 2>/dev/null || true
                  printf 'service=\n'
                  timeout 2s systemctl --no-pager --full status plymouth-start.service 2>&1 || true
                } > /run/plmf/test-failure
                exit 1
              fi
              printf 'active-after-unlock\n' > /run/plmf/plymouth-active
              printf 'complete\n' > /run/plmf/plymouth-test-success
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
            path = with pkgs; [ coreutils procps systemd config.boot.plymouth.package ];
            unitConfig.DefaultDependencies = false;
            serviceConfig = {
              Type = "oneshot";
              TimeoutStartSec = "8s";
            };
            script = ''
              set -eu

              marker_dir=/sysroot/var/lib/plmf-test
              mkdir -p "$marker_dir"
              if [ ! -s /run/plmf/test-failure ] && \
                [ ! -r /run/plmf/plymouth-test-success ]; then
                {
                  printf 'reason=empty-or-missing-test-failure\n'
                  printf 'test-unit=\n'
                  timeout 2s systemctl show \
                    --property=ActiveState,SubState,Result,ExecMainCode,ExecMainStatus \
                    plmf-test-plymouth-after-unlock.service 2>&1 || true
                  printf 'plymouth-unit=\n'
                  timeout 2s systemctl show \
                    --property=ActiveState,SubState,Result,ExecMainCode,ExecMainStatus \
                    plymouth-start.service 2>&1 || true
                  printf 'pid='; cat /run/plymouth/pid 2>/dev/null || true
                  printf 'processes=\n'
                  pgrep -af plymouth 2>/dev/null || true
                  printf 'socket-dir=\n'
                  ls -la /run/plymouth 2>/dev/null || true
                  printf 'config=\n'
                  cat /etc/plymouth/plymouthd.conf 2>/dev/null || true
                  printf 'run-debug=\n'
                  cat /run/plmf/plymouth-debug.log 2>/dev/null || true
                  printf 'var-debug=\n'
                  cat /var/log/plymouth-debug.log 2>/dev/null || true
                  printf 'tmp-debug=\n'
                  cat /tmp/plymouth-debug.log 2>/dev/null || true
                } > /run/plmf/test-failure
              fi
              for marker in \
                effective-theme \
                plymouth-before-unlock \
                password-phase \
                unlock-phase \
                plymouth-active \
                plymouth-test-success \
                plymouth-debug.log; do
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
                if [ -r "$marker_dir/test-failure" ]; then
                  printf 'initrd-test=\n' >> /tmp/xchg/plmf-failure
                  cat "$marker_dir/test-failure" >> /tmp/xchg/plmf-failure
                fi
                printf 'expected=%s\n' "$expected" >> /tmp/xchg/plmf-failure
                printf 'actual=' >> /tmp/xchg/plmf-failure
                cat "$marker_dir/effective-theme" >> /tmp/xchg/plmf-failure 2>/dev/null || true
                printf 'effective-theme=' >&2
                cat "$marker_dir/effective-theme" >&2 2>/dev/null || true
                printf 'initrd-test=' >&2
                cat "$marker_dir/test-failure" >&2 2>/dev/null || true
                printf 'plymouth-debug=' >&2
                cat "$marker_dir/plymouth-debug.log" >&2 2>/dev/null || true
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
              if [ ! -r "$marker_dir/password-phase" ] || \
                [ "$(cat "$marker_dir/password-phase")" != started ]; then
                fail password-phase-marker-missing
              fi
              systemctl is-active --quiet plmf-ask-password-console.service || fail password-agent-inactive
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
                printf 'password-phase=started\n'
                printf 'password-agent=active\n'
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
