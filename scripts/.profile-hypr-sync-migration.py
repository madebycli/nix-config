#!/usr/bin/env python3
from pathlib import Path


def replace(path: str, old: str, new: str) -> None:
    target = Path(path)
    text = target.read_text()
    if old not in text:
        raise SystemExit(f"expected text not found in {path}: {old!r}")
    target.write_text(text.replace(old, new, 1))


replace(
    "flake.nix",
    '''          hostSpecialArgs = host.specialArgs or { };
          homeImports = [ ./modules/home ]
''',
    '''          hostSpecialArgs = host.specialArgs or { };
          profileName =
            if shell == "caelestia" then "${hostName}-hyprland-caelestia"
            else if desktops == [ "mango" ] then hostName
            else if desktops == [ "mango" "niri" "hyprland" ] then "${hostName}-all"
            else "${hostName}-${builtins.concatStringsSep "-" desktops}";
          homeImports = [ ./modules/home ]
''',
)
replace(
    "flake.nix",
    '''                {
                  home-manager = {
''',
    '''                {
                  environment.etc."nixos-config/profile".text = "${profileName}\\n";

                  home-manager = {
''',
)
replace(
    "flake.nix",
    '''        runtimeInputs = with pkgs; [ coreutils findutils git jq nix ];
        text = builtins.readFile ./scripts/nix-refresh.sh;
''',
    '''        runtimeInputs = with pkgs; [ coreutils findutils gh git jq nix ];
        text = builtins.readFile ./scripts/nix-refresh.sh;
''',
)

Path("modules/home/hyprland.nix").write_text('''{ config, lib, pkgs, ... }:

let
  defaultConfig = ../../config/home/.config/hypr/hyprland.conf;
in
{
  home.activation.hyprlandConfig = lib.hm.dag.entryAfter [ "linkGeneration" ] ''
    config_dir="${config.home.homeDirectory}/.config/hypr"
    config_file="$config_dir/hyprland.conf"

    if [ -L "$config_file" ]; then
      target="$(${pkgs.coreutils}/bin/readlink -f "$config_file" 2>/dev/null || true)"
      case "$target" in
        /nix/store/*)
          $DRY_RUN_CMD ${pkgs.coreutils}/bin/rm -f "$config_file"
          ;;
      esac
    fi

    if [ ! -e "$config_file" ]; then
      $DRY_RUN_CMD ${pkgs.coreutils}/bin/mkdir -p "$config_dir"
      $DRY_RUN_CMD ${pkgs.coreutils}/bin/cp ${defaultConfig} "$config_file"
      $DRY_RUN_CMD ${pkgs.coreutils}/bin/chmod u+w "$config_file"
    fi
  '';
}
''')

hypr = Path("config/home/.config/hypr/hyprland.conf")
hypr.parent.mkdir(parents=True, exist_ok=True)
hypr.write_text('''$mod = SUPER

monitor = ,preferred,auto,1

input {
    kb_layout = de
    follow_mouse = 1
}

bind = $mod, Return, exec, ghostty
bind = $mod, D, exec, fuzzel
bind = $mod SHIFT, Q, killactive
bind = $mod SHIFT, E, exit
bind = $mod, F, fullscreen
''')

paths = Path("sync/paths.conf")
text = paths.read_text()
if ".config/hypr\n" not in text:
    paths.write_text(text.replace(".config/mango\n", ".config/mango\n.config/hypr\n"))

replace(
    "modules/nixos/desktop.nix",
    '''    git
    jq
''',
    '''    git
    gh
    jq
''',
)

update = Path("scripts/update.sh")
text = update.read_text()
old = '''if ((SELECTION_EXPLICIT == 0)); then
  PROFILE="$HOST"
  while IFS= read -r state_file; do
    [[ -f "$state_file" ]] || continue
    state_repo="$(jq -r '.repository // empty' "$state_file" 2>/dev/null || true)"
    [[ "$state_repo" == "$REPO" ]] || continue
    candidate="$(jq -r '.profile // empty' "$state_file" 2>/dev/null || true)"
    case "$candidate" in
      "$HOST"|"$HOST-mango"|"$HOST-niri"|"$HOST-hyprland"|"$HOST-hyprland-caelestia"|"$HOST-mango-niri"|"$HOST-mango-hyprland"|"$HOST-niri-hyprland"|"$HOST-all")
        PROFILE="$candidate"
        break
        ;;
    esac
  done < <(find "$HOME/.local/state/nixos-config" -name state.json -type f 2>/dev/null || true)
else
'''
new = '''if ((SELECTION_EXPLICIT == 0)); then
  PROFILE="$HOST"
  PROFILE_FROM_SYSTEM=0
  if [[ -r /etc/nixos-config/profile ]]; then
    candidate="$(tr -d '\\r\\n' </etc/nixos-config/profile)"
    case "$candidate" in
      "$HOST"|"$HOST-mango"|"$HOST-niri"|"$HOST-hyprland"|"$HOST-hyprland-caelestia"|"$HOST-mango-niri"|"$HOST-mango-hyprland"|"$HOST-niri-hyprland"|"$HOST-all")
        PROFILE="$candidate"
        PROFILE_FROM_SYSTEM=1
        ;;
    esac
  fi
  if ((PROFILE_FROM_SYSTEM == 0)); then
    while IFS= read -r state_file; do
      [[ -f "$state_file" ]] || continue
      state_repo="$(jq -r '.repository // empty' "$state_file" 2>/dev/null || true)"
      [[ "$state_repo" == "$REPO" ]] || continue
      candidate="$(jq -r '.profile // empty' "$state_file" 2>/dev/null || true)"
      case "$candidate" in
        "$HOST"|"$HOST-mango"|"$HOST-niri"|"$HOST-hyprland"|"$HOST-hyprland-caelestia"|"$HOST-mango-niri"|"$HOST-mango-hyprland"|"$HOST-niri-hyprland"|"$HOST-all")
          PROFILE="$candidate"
          break
          ;;
      esac
    done < <(find "$HOME/.local/state/nixos-config" -name state.json -type f 2>/dev/null || true)
  fi
else
'''
if old not in text:
    raise SystemExit("profile selection block not found in scripts/update.sh")
text = text.replace(old, new, 1)

old = '''read -r AHEAD BEHIND < <(git -C "$REPO" rev-list --left-right --count "HEAD...$UPSTREAM")
((AHEAD == 0 || BEHIND == 0)) || die "Git history diverged."

STASHED=0
'''
new = '''read -r AHEAD BEHIND < <(git -C "$REPO" rev-list --left-right --count "HEAD...$UPSTREAM")

if ((AHEAD > 0 && BEHIND > 0)); then
  AUTO_LOCK_ONLY=1
  while IFS= read -r commit; do
    subject="$(git -C "$REPO" show -s --format=%s "$commit")"
    case "$subject" in
      update\\(*\\):\\ refresh\\ Flake\\ inputs) ;;
      *) AUTO_LOCK_ONLY=0; break ;;
    esac
    mapfile -t commit_paths < <(git -C "$REPO" diff-tree --root --no-commit-id --name-only -r "$commit")
    if ((${#commit_paths[@]} != 1)) || [[ "${commit_paths[0]}" != "flake.lock" ]]; then
      AUTO_LOCK_ONLY=0
      break
    fi
  done < <(git -C "$REPO" rev-list "$UPSTREAM..HEAD")

  if ((AUTO_LOCK_ONLY == 1)); then
    printf '\\n==> Rebasing local automatic Flake update commit(s)\\n'
    if ! git -C "$REPO" rebase "$UPSTREAM"; then
      git -C "$REPO" rebase --abort >/dev/null 2>&1 || true
      die "Automatic rebase of local Flake update commit(s) failed."
    fi
    read -r AHEAD BEHIND < <(git -C "$REPO" rev-list --left-right --count "HEAD...$UPSTREAM")
  else
    die "Git history diverged."
  fi
fi

STASHED=0
'''
if old not in text:
    raise SystemExit("divergence block not found in scripts/update.sh")
update.write_text(text.replace(old, new, 1))


def patch_profile_resolution(path: str, host_var: str, repo_var: str) -> None:
    target = Path(path)
    text = target.read_text()
    old = f'''PROFILE="${{{host_var}}}"
while IFS= read -r state_file; do
  [[ -f "$state_file" ]] || continue
  state_repo="$(jq -r '.repository // empty' "$state_file" 2>/dev/null || true)"
  [[ "$state_repo" == "${{{repo_var}}}" ]] || continue
  candidate="$(jq -r '.profile // empty' "$state_file" 2>/dev/null || true)"
  case "$candidate" in
    "${{{host_var}}}"|"${{{host_var}}}-mango"|"${{{host_var}}}-niri"|"${{{host_var}}}-hyprland"|"${{{host_var}}}-hyprland-caelestia"|"${{{host_var}}}-mango-niri"|"${{{host_var}}}-mango-hyprland"|"${{{host_var}}}-niri-hyprland"|"${{{host_var}}}-all") PROFILE="$candidate" ;;
  esac
  break
done < <(find "$HOME/.local/state/nixos-config" -name state.json -type f 2>/dev/null || true)
'''
    new = f'''PROFILE="${{{host_var}}}"
PROFILE_FROM_SYSTEM=0
if [[ -r /etc/nixos-config/profile ]]; then
  candidate="$(tr -d '\\r\\n' </etc/nixos-config/profile)"
  case "$candidate" in
    "${{{host_var}}}"|"${{{host_var}}}-mango"|"${{{host_var}}}-niri"|"${{{host_var}}}-hyprland"|"${{{host_var}}}-hyprland-caelestia"|"${{{host_var}}}-mango-niri"|"${{{host_var}}}-mango-hyprland"|"${{{host_var}}}-niri-hyprland"|"${{{host_var}}}-all") PROFILE="$candidate"; PROFILE_FROM_SYSTEM=1 ;;
  esac
fi
if ((PROFILE_FROM_SYSTEM == 0)); then
  while IFS= read -r state_file; do
    [[ -f "$state_file" ]] || continue
    state_repo="$(jq -r '.repository // empty' "$state_file" 2>/dev/null || true)"
    [[ "$state_repo" == "${{{repo_var}}}" ]] || continue
    candidate="$(jq -r '.profile // empty' "$state_file" 2>/dev/null || true)"
    case "$candidate" in
      "${{{host_var}}}"|"${{{host_var}}}-mango"|"${{{host_var}}}-niri"|"${{{host_var}}}-hyprland"|"${{{host_var}}}-hyprland-caelestia"|"${{{host_var}}}-mango-niri"|"${{{host_var}}}-mango-hyprland"|"${{{host_var}}}-niri-hyprland"|"${{{host_var}}}-all") PROFILE="$candidate" ;;
    esac
    break
  done < <(find "$HOME/.local/state/nixos-config" -name state.json -type f 2>/dev/null || true)
fi
'''
    if old not in text:
        raise SystemExit(f"profile resolution block not found in {path}")
    target.write_text(text.replace(old, new, 1))


patch_profile_resolution("scripts/nix-refresh.sh", "HOST", "REPO")
patch_profile_resolution("scripts/nix-updates.sh", "host", "repo")

status = Path("scripts/nix-status.sh")
text = status.read_text()
old = '''profile="$host"
if [[ -d "$HOME/.local/state/nixos-config" ]]; then
  while IFS= read -r state_file; do
    state_repo="$(jq -r '.repository // empty' "$state_file" 2>/dev/null || true)"
    [[ "$state_repo" == "$repo" ]] || continue
    candidate="$(jq -r '.profile // empty' "$state_file" 2>/dev/null || true)"
    case "$candidate" in
      "$host"|"$host-mango"|"$host-niri"|"$host-hyprland"|"$host-hyprland-caelestia"|"$host-mango-niri"|"$host-mango-hyprland"|"$host-niri-hyprland"|"$host-all") profile="$candidate" ;;
    esac
    break
  done < <(find "$HOME/.local/state/nixos-config" -name state.json -type f 2>/dev/null || true)
fi
'''
new = '''profile="$host"
profile_from_system=0
if [[ -r /etc/nixos-config/profile ]]; then
  candidate="$(tr -d '\\r\\n' </etc/nixos-config/profile)"
  case "$candidate" in
    "$host"|"$host-mango"|"$host-niri"|"$host-hyprland"|"$host-hyprland-caelestia"|"$host-mango-niri"|"$host-mango-hyprland"|"$host-niri-hyprland"|"$host-all") profile="$candidate"; profile_from_system=1 ;;
  esac
fi
if ((profile_from_system == 0)) && [[ -d "$HOME/.local/state/nixos-config" ]]; then
  while IFS= read -r state_file; do
    state_repo="$(jq -r '.repository // empty' "$state_file" 2>/dev/null || true)"
    [[ "$state_repo" == "$repo" ]] || continue
    candidate="$(jq -r '.profile // empty' "$state_file" 2>/dev/null || true)"
    case "$candidate" in
      "$host"|"$host-mango"|"$host-niri"|"$host-hyprland"|"$host-hyprland-caelestia"|"$host-mango-niri"|"$host-mango-hyprland"|"$host-niri-hyprland"|"$host-all") profile="$candidate" ;;
    esac
    break
  done < <(find "$HOME/.local/state/nixos-config" -name state.json -type f 2>/dev/null || true)
fi
'''
if old not in text:
    raise SystemExit("profile block not found in scripts/nix-status.sh")
status.write_text(text.replace(old, new, 1))

refresh = Path("scripts/nix-refresh.sh")
text = refresh.read_text()
old = '''PUBLISH=1
((AHEAD == 0)) || PUBLISH=0
[[ -n "$(git -C "$REPO" config user.name || true)" ]] || PUBLISH=0
[[ -n "$(git -C "$REPO" config user.email || true)" ]] || PUBLISH=0
'''
new = '''PUBLISH=1
if ((AHEAD > 0)); then
  while IFS= read -r commit; do
    subject="$(git -C "$REPO" show -s --format=%s "$commit")"
    case "$subject" in
      update\\(*\\):\\ refresh\\ Flake\\ inputs) ;;
      *) PUBLISH=0; break ;;
    esac
    mapfile -t commit_paths < <(git -C "$REPO" diff-tree --root --no-commit-id --name-only -r "$commit")
    if ((${#commit_paths[@]} != 1)) || [[ "${commit_paths[0]}" != "flake.lock" ]]; then
      PUBLISH=0
      break
    fi
  done < <(git -C "$REPO" rev-list "$UPSTREAM..HEAD")
fi
[[ -n "$(git -C "$REPO" config user.name || true)" ]] || PUBLISH=0
[[ -n "$(git -C "$REPO" config user.email || true)" ]] || PUBLISH=0
'''
if old not in text:
    raise SystemExit("publish block not found in scripts/nix-refresh.sh")
text = text.replace(old, new, 1)

old = '''if ! git -C "$REPO" diff --quiet -- flake.lock; then
  if ((PUBLISH == 1)); then
    git -C "$REPO" add -- flake.lock
    if git -C "$REPO" commit -m "update($MODE): refresh Flake inputs"; then
      git -C "$REPO" fetch --prune origin
      read -r PUSH_AHEAD PUSH_BEHIND < <(git -C "$REPO" rev-list --left-right --count "HEAD...$UPSTREAM")
      if ((PUSH_BEHIND == 0)); then
        git -C "$REPO" push origin "$BRANCH" || printf 'Git push failed; commit remains local.\\n' >&2
      else
        printf 'Remote advanced; commit remains local.\\n' >&2
      fi
    else
      git -C "$REPO" reset -q HEAD -- flake.lock || true
      printf 'Lock-file commit failed.\\n' >&2
    fi
  else
    printf 'flake.lock remains modified locally.\\n' >&2
  fi
fi
'''
new = '''if ! git -C "$REPO" diff --quiet -- flake.lock; then
  if ((PUBLISH == 1)); then
    git -C "$REPO" add -- flake.lock
    if ! git -C "$REPO" commit -m "update($MODE): refresh Flake inputs"; then
      git -C "$REPO" reset -q HEAD -- flake.lock || true
      printf 'Lock-file commit failed.\\n' >&2
      PUBLISH=0
    fi
  else
    printf 'flake.lock remains modified locally.\\n' >&2
  fi
fi

if ((PUBLISH == 1)); then
  git -C "$REPO" fetch --prune origin
  read -r PUSH_AHEAD PUSH_BEHIND < <(git -C "$REPO" rev-list --left-right --count "HEAD...$UPSTREAM")
  if ((PUSH_BEHIND > 0)); then
    printf 'Remote advanced; local Flake update commit remains local.\\n' >&2
  elif ((PUSH_AHEAD > 0)); then
    if gh auth status --hostname github.com >/dev/null 2>&1; then
      gh auth setup-git --hostname github.com >/dev/null 2>&1 || true
      if ! GIT_TERMINAL_PROMPT=0 git -C "$REPO" push origin "$BRANCH"; then
        printf 'GitHub push failed; commit remains local.\\n' >&2
      fi
    else
      printf 'GitHub push skipped; authenticate once with: gh auth login --hostname github.com --git-protocol https --web\\n' >&2
    fi
  fi
fi
'''
if old not in text:
    raise SystemExit("push block not found in scripts/nix-refresh.sh")
refresh.write_text(text.replace(old, new, 1))

sync = Path("scripts/config-sync.py")
text = sync.read_text()
old = '''def profile_from_state(repo: Path, explicit: str | None) -> str:
    if explicit:
        return explicit
    state = load_state(repo)
    if state.get("profile"):
        return str(state["profile"])
    return socket.gethostname().split(".", 1)[0]
'''
new = '''def profile_from_state(repo: Path, explicit: str | None) -> str:
    if explicit:
        return explicit
    system_profile = Path("/etc/nixos-config/profile")
    if system_profile.is_file():
        value = system_profile.read_text(encoding="utf-8").strip()
        if value:
            return value
    state = load_state(repo)
    if state.get("profile"):
        return str(state["profile"])
    return socket.gethostname().split(".", 1)[0]
'''
if old not in text:
    raise SystemExit("profile_from_state block not found")
text = text.replace(old, new, 1)
text = text.replace(
    'save_state(repo, common, args.profile or socket.gethostname().split(".", 1)[0])',
    'save_state(repo, common, profile_from_state(repo, args.profile))',
)
sync.write_text(text)
