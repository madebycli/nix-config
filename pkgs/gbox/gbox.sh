# gbox - run games, Wine prefixes and untrusted programs in a bubblewrap sandbox.
#
# Threat model: the program is not trusted. It gets no access to $HOME, no
# D-Bus, no host X11/Wayland socket, no host network namespace and only the
# devices and folders you list. See `gbox help`.

readonly GBOX_ETC_PROFILES="${GBOX_ETC_PROFILES:-/etc/gbox/profiles}"
readonly CONF_HOME="${XDG_CONFIG_HOME:-$HOME/.config}/gbox"
readonly DATA_HOME="${XDG_DATA_HOME:-$HOME/.local/share}/gbox"
readonly DNS_ADDR="10.255.255.53"

die() {
  echo "gbox: $*" >&2
  exit 1
}

usage() {
  cat <<'EOF'
gbox - sandbox for games, Wine and untrusted programs

Usage:
  gbox new   NAME [options] [-- COMMAND...]   create or replace a profile
  gbox run   NAME [options] [-- COMMAND...]   start a profile (options apply once)
  gbox wine  NAME [options] -- PROGRAM.exe... run a Windows program with Wine
  gbox shell NAME [options]                   shell inside the sandbox
  gbox list | show NAME | edit NAME | path NAME
  gbox rm NAME [--purge]                      delete the profile (--purge: also its data)

Options:
  --net none|inet|lan     none: no network (default)
                          inet: internet only, LAN/localhost blocked
                          lan:  internet and local network
                          Both network modes use a private network namespace;
                          the host's loopback and abstract sockets stay out of reach.
  --display gamescope|wayland|none
                          gamescope: isolated display via a host-side gamescope (default)
                          wayland:   host Wayland socket (UNSAFE: screen capture,
                                     input injection possible on wlroots compositors)
                          none:      no display
  --gamescope-args "ARGS" extra gamescope arguments, e.g. "-W 2560 -H 1440 -r 144 -f"
  --no-gpu                no GPU access (software rendering)
  --no-audio              no sound (PipeWire exposes the microphone to clients)
  --hud                   MangoHud overlay (gamescope display only)
  --share PATH            read-write folder, same path inside (repeatable)
  --ro PATH               read-only folder, same path inside (repeatable)
  --dev PATH              device node, e.g. a gamepad /dev/input/event12 (repeatable)
  --env KEY=VALUE         environment variable (repeatable)

Data lives in ~/.local/share/gbox/NAME/home and is the program's $HOME.
Profiles live in ~/.config/gbox/profiles (or /etc/gbox/profiles, declared in Nix).
EOF
}

# ---------------------------------------------------------------- profiles

profile_file() {
  local name="$1"
  [[ "$name" =~ ^[A-Za-z0-9][A-Za-z0-9._-]*$ ]] || die "invalid profile name: $name"
  if [[ -f "$CONF_HOME/profiles/$name.conf" ]]; then
    echo "$CONF_HOME/profiles/$name.conf"
  elif [[ -f "$GBOX_ETC_PROFILES/$name.conf" ]]; then
    echo "$GBOX_ETC_PROFILES/$name.conf"
  else
    return 1
  fi
}

reset_profile() {
  NET=none
  DISPLAY_MODE=gamescope
  GPU=1
  AUDIO=1
  HUD=0
  GS_ARGS=""
  SHARE=()
  RO=()
  DEV=()
  ENVV=()
  CMD=()
}

# Profiles are key=value lines, never sourced as shell.
load_profile() {
  local file="$1" line key value
  while IFS= read -r line || [[ -n "$line" ]]; do
    [[ -z "$line" || "$line" == \#* ]] && continue
    key="${line%%=*}"
    value="${line#*=}"
    case "$key" in
      net) set_net "$value" ;;
      display) set_display "$value" ;;
      gpu) GPU="$value" ;;
      audio) AUDIO="$value" ;;
      hud) HUD="$value" ;;
      gamescope-args) GS_ARGS="$value" ;;
      share) SHARE+=("$value") ;;
      ro) RO+=("$value") ;;
      dev) DEV+=("$value") ;;
      env) ENVV+=("$value") ;;
      cmd) CMD+=("$value") ;;
      *) die "unknown key '$key' in $file" ;;
    esac
  done <"$file"
}

set_net() {
  case "$1" in
    none | inet | lan) NET="$1" ;;
    *) die "--net expects none, inet or lan (got '$1')" ;;
  esac
}

set_display() {
  case "$1" in
    gamescope | wayland | none) DISPLAY_MODE="$1" ;;
    *) die "--display expects gamescope, wayland or none (got '$1')" ;;
  esac
}

# Parses options shared by new/run/wine/shell. Remaining args after `--` go to CMD_ARGS.
parse_options() {
  CMD_ARGS=()
  HAVE_CMD=0
  while [[ $# -gt 0 ]]; do
    case "$1" in
      --net) set_net "${2:?--net needs a value}"; shift 2 ;;
      --display) set_display "${2:?--display needs a value}"; shift 2 ;;
      --gamescope-args) GS_ARGS="${2:?--gamescope-args needs a value}"; shift 2 ;;
      --no-gpu) GPU=0; shift ;;
      --gpu) GPU=1; shift ;;
      --no-audio) AUDIO=0; shift ;;
      --audio) AUDIO=1; shift ;;
      --hud) HUD=1; shift ;;
      --share) SHARE+=("${2:?--share needs a path}"); shift 2 ;;
      --ro) RO+=("${2:?--ro needs a path}"); shift 2 ;;
      --dev) DEV+=("${2:?--dev needs a path}"); shift 2 ;;
      --env) ENVV+=("${2:?--env needs KEY=VALUE}"); shift 2 ;;
      --) shift; CMD_ARGS=("$@"); HAVE_CMD=1; return ;;
      *) die "unknown option: $1 (see gbox help)" ;;
    esac
  done
}

write_profile() {
  local name="$1" file dir
  local item
  for item in "${CMD[@]}" "${SHARE[@]}" "${RO[@]}" "${DEV[@]}" "${ENVV[@]}" "$GS_ARGS"; do
    [[ "$item" != *$'\n'* ]] || die "newlines are not supported in profile values (put the commands in a script file)"
  done
  dir="$CONF_HOME/profiles"
  file="$dir/$name.conf"
  mkdir -p "$dir"
  {
    echo "# gbox profile $name"
    echo "net=$NET"
    echo "display=$DISPLAY_MODE"
    echo "gpu=$GPU"
    echo "audio=$AUDIO"
    echo "hud=$HUD"
    [[ -n "$GS_ARGS" ]] && echo "gamescope-args=$GS_ARGS"
    local p
    for p in "${SHARE[@]}"; do echo "share=$p"; done
    for p in "${RO[@]}"; do echo "ro=$p"; done
    for p in "${DEV[@]}"; do echo "dev=$p"; done
    for p in "${ENVV[@]}"; do echo "env=$p"; done
    for p in "${CMD[@]}"; do echo "cmd=$p"; done
  } >"$file"
  echo "gbox: wrote $file"
}

# ---------------------------------------------------------------- validation

check_path() {
  local kind="$1" path="$2" real
  [[ "$path" == /* ]] || die "$kind path must be absolute: $path"
  real="$(realpath -e -- "$path" 2>/dev/null)" || die "$kind path does not exist: $path"
  case "$real" in
    / | /etc | /run | /proc | /sys | /dev | /var | /nix | /boot | /root | /usr | /bin)
      die "refusing to expose $real"
      ;;
  esac
  if [[ "$real" == "$HOME" || "$HOME" == "$real"/* ]]; then
    die "refusing to expose your home folder or one of its parents: $real"
  fi
  case "$real" in
    "$HOME"/.ssh* | "$HOME"/.gnupg* | "$HOME"/.config | "$HOME"/.local/share/keyrings*)
      die "refusing to expose a credential folder: $real"
      ;;
  esac
  echo "$real"
}

# ---------------------------------------------------------------- launch

launch() {
  local name="$1"
  mkdir -p "$DATA_HOME/$name/home"
  GBOX_STATE="$(declare -p name NET DISPLAY_MODE GPU AUDIO HUD GS_ARGS SHARE RO DEV ENVV CMD)"
  export GBOX_STATE
  GBOX_HOST_WAYLAND="${WAYLAND_DISPLAY:-}"
  export GBOX_HOST_WAYLAND

  local self
  self="$(readlink -f "$0")"

  if [[ "$DISPLAY_MODE" == gamescope ]]; then
    [[ -n "${WAYLAND_DISPLAY:-}" ]] || die "gamescope display needs a running Wayland session"
    local gs=gamescope
    [[ -x /run/wrappers/bin/gamescope ]] && gs=/run/wrappers/bin/gamescope
    local gs_args=(--expose-wayland)
    [[ "$HUD" == 1 ]] && gs_args+=(--mangoapp)
    if [[ -n "$GS_ARGS" ]]; then
      local extra
      read -r -a extra <<<"$GS_ARGS"
      gs_args+=("${extra[@]}")
    fi
    exec "$gs" "${gs_args[@]}" -- "$self" __sandbox
  fi
  exec "$self" __sandbox
}

# shellcheck disable=SC2154  # variables come from GBOX_STATE
sandbox() {
  eval "$GBOX_STATE"

  local uid gid user rt sbhome
  uid="$(id -u)"
  gid="$(id -g)"
  user="$(id -un)"
  rt="/run/user/$uid"
  sbhome="$DATA_HOME/$name/home"
  tmpd="$(mktemp -d)"
  trap 'rm -rf -- "$tmpd"' EXIT

  printf '%s:x:%s:%s:%s:%s:/bin/sh\nnobody:x:65534:65534:nobody:/var/empty:/bin/false\n' \
    "$user" "$uid" "$gid" "$user" "$HOME" >"$tmpd/passwd"
  printf '%s:x:%s:\nnogroup:x:65534:\n' "$user" "$gid" >"$tmpd/group"
  if [[ ! -f "$DATA_HOME/$name/machine-id" ]]; then
    # Stable per profile, unrelated to the host's identity.
    od -An -N16 -tx1 /dev/urandom | tr -d ' \n' >"$DATA_HOME/$name/machine-id"
    echo >>"$DATA_HOME/$name/machine-id"
  fi

  local b=(
    bwrap
    --unshare-user --unshare-ipc --unshare-pid --unshare-uts --unshare-cgroup-try
    --uid "$uid" --gid "$gid" --hostname "gbox-$name"
    --die-with-parent --new-session --cap-drop ALL
    --proc /proc --dev /dev
    --tmpfs /tmp
    --perms 0700 --tmpfs "$rt"
    --ro-bind /nix/store /nix/store
    --ro-bind-try /etc/static /etc/static
    --ro-bind-try /etc/fonts /etc/fonts
    --ro-bind-try /etc/ssl /etc/ssl
    --ro-bind-try /etc/nsswitch.conf /etc/nsswitch.conf
    --ro-bind-try /etc/localtime /etc/localtime
    --ro-bind "$tmpd/passwd" /etc/passwd
    --ro-bind "$tmpd/group" /etc/group
    --ro-bind "$DATA_HOME/$name/machine-id" /etc/machine-id
    --bind "$sbhome" "$HOME"
    --clearenv
    --setenv HOME "$HOME" --setenv USER "$user" --setenv LOGNAME "$user"
    --setenv PATH "$PATH" --setenv XDG_RUNTIME_DIR "$rt"
    --setenv LANG "${LANG:-C.UTF-8}"
    --setenv SSL_CERT_FILE /etc/ssl/certs/ca-bundle.crt
    --setenv XDG_DATA_DIRS /run/opengl-driver/share
    --setenv GBOX_PROFILE "$name"
  )
  [[ -n "${LOCALE_ARCHIVE:-}" ]] && b+=(--setenv LOCALE_ARCHIVE "$LOCALE_ARCHIVE")
  [[ -n "${TZ:-}" ]] && b+=(--setenv TZ "$TZ")

  # --- network -----------------------------------------------------------
  local wrap=()
  if [[ "$NET" == none ]]; then
    b+=(--unshare-net)
  else
    # Own network namespace fed by pasta: no access to host loopback or to
    # abstract sockets (X11, D-Bus) of the host.
    printf 'nameserver %s\n' "$DNS_ADDR" >"$tmpd/resolv.conf"
    b+=(--ro-bind "$tmpd/resolv.conf" /etc/resolv.conf)
    wrap=(
      pasta --quiet --config-net --no-map-gw
      -t none -u none -T none -U none
      --dns-forward "$DNS_ADDR"
      --
      "$tmpd/netsetup" "$NET"
    )
    cat >"$tmpd/netsetup" <<'NETSETUP'
#!/usr/bin/env bash
set -eu
mode="$1"; shift
if [ "$mode" = inet ]; then
  nft -f - <<RULES
table inet gbox {
  chain out {
    type filter hook output priority 0; policy accept;
    oifname "lo" accept
    ip daddr 10.255.255.53 accept
    ip daddr { 0.0.0.0/8, 10.0.0.0/8, 100.64.0.0/10, 127.0.0.0/8, 169.254.0.0/16, 172.16.0.0/12, 192.0.0.0/24, 192.168.0.0/16, 198.18.0.0/15, 224.0.0.0/4, 240.0.0.0/4 } drop
    ip6 daddr { ::1, fc00::/7, fe80::/10, ff00::/8 } drop
  }
}
RULES
fi
exec "$@"
NETSETUP
    chmod +x "$tmpd/netsetup"
  fi

  # --- display -----------------------------------------------------------
  case "$DISPLAY_MODE" in
    gamescope)
      [[ -n "${WAYLAND_DISPLAY:-}" && "$WAYLAND_DISPLAY" != "$GBOX_HOST_WAYLAND" ]] ||
        die "gamescope did not expose its own Wayland socket; refusing to fall back to the host socket"
      b+=(--ro-bind "$rt/$WAYLAND_DISPLAY" "$rt/$WAYLAND_DISPLAY"
        --setenv WAYLAND_DISPLAY "$WAYLAND_DISPLAY")
      if [[ -n "${DISPLAY:-}" ]]; then
        local xnum="${DISPLAY#:}"
        xnum="${xnum%%.*}"
        b+=(--ro-bind "/tmp/.X11-unix/X$xnum" "/tmp/.X11-unix/X$xnum"
          --setenv DISPLAY ":$xnum")
      fi
      ;;
    wayland)
      [[ -n "${WAYLAND_DISPLAY:-}" ]] || die "no Wayland session"
      b+=(--ro-bind "$rt/$WAYLAND_DISPLAY" "$rt/$WAYLAND_DISPLAY"
        --setenv WAYLAND_DISPLAY "$WAYLAND_DISPLAY")
      ;;
    none) ;;
  esac

  # --- gpu ---------------------------------------------------------------
  if [[ "$GPU" == 1 ]]; then
    b+=(--ro-bind-try /run/opengl-driver /run/opengl-driver
      --ro-bind-try /run/opengl-driver-32 /run/opengl-driver-32
      --ro-bind-try /sys/dev /sys/dev
      --ro-bind-try /sys/devices /sys/devices
      --ro-bind-try /sys/class/drm /sys/class/drm
      --dev-bind-try /dev/dri /dev/dri)
    local node
    for node in /dev/nvidia*; do
      [[ -e "$node" ]] && b+=(--dev-bind "$node" "$node")
    done
  fi

  # --- audio -------------------------------------------------------------
  if [[ "$AUDIO" == 1 ]]; then
    b+=(--ro-bind-try "$rt/pipewire-0" "$rt/pipewire-0"
      --ro-bind-try "$rt/pulse/native" "$rt/pulse/native"
      --setenv PULSE_SERVER "unix:$rt/pulse/native")
  fi

  # --- folders, devices, variables ---------------------------------------
  local p real kv
  for p in "${SHARE[@]}"; do
    real="$(check_path share "$p")"
    b+=(--bind "$real" "$real")
  done
  for p in "${RO[@]}"; do
    real="$(check_path ro "$p")"
    b+=(--ro-bind "$real" "$real")
  done
  for p in "${DEV[@]}"; do
    [[ "$p" == /dev/* && -e "$p" ]] || die "device not found: $p"
    b+=(--dev-bind "$p" "$p")
  done
  for kv in "${ENVV[@]}"; do
    [[ "$kv" == *=* ]] || die "env needs KEY=VALUE: $kv"
    b+=(--setenv "${kv%%=*}" "${kv#*=}")
  done

  [[ ${#CMD[@]} -gt 0 ]] || die "profile '$name' has no command (use -- COMMAND...)"

  local rc=0
  if [[ ${#wrap[@]} -gt 0 ]]; then
    "${wrap[@]}" "${b[@]}" -- "${CMD[@]}" || rc=$?
  else
    "${b[@]}" -- "${CMD[@]}" || rc=$?
  fi
  exit "$rc"
}

# ---------------------------------------------------------------- commands

main() {
  local cmd="${1:-help}"
  [[ $# -gt 0 ]] && shift

  case "$cmd" in
    help | -h | --help) usage ;;

    __sandbox) sandbox ;;

    new)
      local name="${1:?usage: gbox new NAME [options] [-- COMMAND...]}"
      shift
      [[ "$name" =~ ^[A-Za-z0-9][A-Za-z0-9._-]*$ ]] || die "invalid profile name: $name"
      reset_profile
      parse_options "$@"
      [[ "$HAVE_CMD" == 1 ]] && CMD=("${CMD_ARGS[@]}")
      write_profile "$name"
      ;;

    run | shell | wine)
      local name="${1:?usage: gbox $cmd NAME [options] [-- COMMAND...]}"
      shift
      local file
      file="$(profile_file "$name")" || die "no profile '$name' (create it with: gbox new $name ...)"
      reset_profile
      load_profile "$file"
      parse_options "$@"
      case "$cmd" in
        run) [[ "$HAVE_CMD" == 1 && ${#CMD_ARGS[@]} -gt 0 ]] && CMD=("${CMD_ARGS[@]}") ;;
        shell) CMD=(bash) ;;
        wine)
          [[ ${#CMD_ARGS[@]} -gt 0 ]] || die "usage: gbox wine NAME [options] -- PROGRAM.exe [args]"
          CMD=(wine "${CMD_ARGS[@]}")
          ENVV+=("WINEPREFIX=$HOME/.wine" "WINEDEBUG=-all")
          ;;
      esac
      launch "$name"
      ;;

    list)
      local f n
      for f in "$CONF_HOME"/profiles/*.conf "$GBOX_ETC_PROFILES"/*.conf; do
        [[ -f "$f" ]] || continue
        n="$(basename "$f" .conf)"
        printf '%-24s %s\n' "$n" "$f"
      done
      ;;

    show)
      local name="${1:?usage: gbox show NAME}"
      cat "$(profile_file "$name")" || die "no profile '$name'"
      ;;

    path)
      echo "$DATA_HOME/${1:?usage: gbox path NAME}/home"
      ;;

    edit)
      local name="${1:?usage: gbox edit NAME}" file
      file="$CONF_HOME/profiles/$name.conf"
      [[ -f "$file" ]] || die "no user profile '$name' (declared profiles are read-only)"
      exec "${EDITOR:-nano}" "$file"
      ;;

    rm)
      local name="${1:?usage: gbox rm NAME [--purge]}" purge="${2:-}"
      rm -f -- "$CONF_HOME/profiles/$name.conf"
      if [[ "$purge" == --purge ]]; then
        rm -rf -- "${DATA_HOME:?}/$name"
        echo "gbox: removed profile and data of $name"
      else
        echo "gbox: removed profile $name (data kept in $DATA_HOME/$name)"
      fi
      ;;

    *) die "unknown command '$cmd' (see gbox help)" ;;
  esac
}

main "$@"
