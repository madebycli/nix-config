# agentbox - control the isolated NixOS VM that runs Claude Code and Codex.

readonly CONF="${AGENTBOX_CONF:-/etc/agentbox.conf}"
[[ -r "$CONF" ]] || { echo "agentbox: missing $CONF (enable my.features.agentbox)" >&2; exit 1; }
VM="" ADDR="" WORKSPACE="" VM_USER=""
# shellcheck disable=SC1090
. "$CONF"

die() {
  echo "agentbox: $*" >&2
  exit 1
}

ssh_args=(-o StrictHostKeyChecking=accept-new -o UserKnownHostsFile="$HOME/.ssh/known_hosts_agentbox" -o ConnectTimeout=5)

running() { systemctl is-active --quiet "microvm@$VM.service"; }

wait_ssh() {
  local attempt
  for ((attempt = 0; attempt < 60; attempt++)); do
    if ssh "${ssh_args[@]}" -o BatchMode=yes "$VM_USER@$ADDR" true 2>/dev/null; then
      return 0
    fi
    sleep 2
  done
  die "VM does not answer on ssh at $ADDR (see: agentbox logs)"
}

usage() {
  cat <<'EOF2'
agentbox - isolated VM for Claude Code and Codex

  agentbox start        boot the VM
  agentbox stop         shut it down
  agentbox status       VM state and address
  agentbox ssh [cmd]    shell (or command) inside the VM
  agentbox code         open VSCodium connected to the VM (/work)
  agentbox logs         follow the VM log
  agentbox reset        delete the VM's home volume (logins, caches); needs --yes

Inside the VM your agents may run without prompts:
  yolo-claude   yolo-codex
Only the shared workspace is visible to the host; the host never exposes
$HOME, its LAN or its loopback services to the VM.
EOF2
}

cmd="${1:-status}"
[[ $# -gt 0 ]] && shift
case "$cmd" in
  help | -h | --help) usage ;;
  start)
    running || sudo systemctl start "microvm@$VM.service"
    wait_ssh
    echo "agentbox: up at $ADDR (workspace on the host: $WORKSPACE)"
    ;;
  stop) sudo systemctl stop "microvm@$VM.service" ;;
  status)
    if running; then
      echo "agentbox: running at $ADDR"
    else
      echo "agentbox: stopped"
    fi
    ;;
  ssh)
    running || die "not running (agentbox start)"
    exec ssh "${ssh_args[@]}" "$VM_USER@$ADDR" "$@"
    ;;
  code)
    running || "$0" start
    command -v codium >/dev/null 2>&1 || die "VSCodium (codium) is not installed"
    if ! codium --list-extensions 2>/dev/null | grep -qix 'jeanp413.open-remote-ssh'; then
      echo "agentbox: installing the Open Remote - SSH extension from Open VSX"
      codium --install-extension jeanp413.open-remote-ssh
    fi
    exec codium --remote "ssh-remote+$VM_USER@$ADDR" /work
    ;;
  logs) exec journalctl -fu "microvm@$VM.service" ;;
  reset)
    [[ "${1:-}" == --yes ]] || die "this deletes the VM home (agent logins, shell history). Re-run: agentbox reset --yes"
    running && sudo systemctl stop "microvm@$VM.service"
    sudo rm -f -- "/var/lib/microvms/$VM/home.img"
    rm -f -- "$HOME/.ssh/known_hosts_agentbox"
    echo "agentbox: home volume removed; the next start creates a fresh one"
    ;;
  *) die "unknown command '$cmd' (see agentbox help)" ;;
esac
