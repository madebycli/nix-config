#!/usr/bin/env python3
from pathlib import Path

source_path = Path("scripts/.profile-hypr-sync-migration-v2.py")
source = source_path.read_text()
start = source.index("def replace_profile_block(path: str, host: str, repo: str) -> None:\n")
end = source.index("\n\nreplace_profile_block(\"scripts/nix-refresh.sh\"", start)

replacement = r'''def replace_profile_block(path: str, host: str, repo: str) -> None:
    target = Path(path)
    text = target.read_text()
    shell_var = "PROFILE" if host == "HOST" else "profile"
    host_ref = f"${host}"
    repo_ref = f"${repo}"
    start_marker = f'{shell_var}="{host_ref}"\nwhile IFS= read -r state_file; do\n'
    end_marker = "\nreadonly PROFILE\n" if host == "HOST" else "\ntemp_root="
    block_start = text.find(start_marker)
    if block_start < 0:
        raise SystemExit(f"profile resolution start not found in {path}")
    block_end = text.find(end_marker, block_start)
    if block_end < 0:
        raise SystemExit(f"profile resolution end not found in {path}")

    new = f'''{shell_var}="{host_ref}"
PROFILE_FROM_SYSTEM=0
if [[ -r /etc/nixos-config/profile ]]; then
  candidate="$(tr -d '\\r\\n' </etc/nixos-config/profile)"
  case "$candidate" in
    "{host_ref}"|"{host_ref}-mango"|"{host_ref}-niri"|"{host_ref}-hyprland"|"{host_ref}-hyprland-caelestia"|"{host_ref}-mango-niri"|"{host_ref}-mango-hyprland"|"{host_ref}-niri-hyprland"|"{host_ref}-all") {shell_var}="$candidate"; PROFILE_FROM_SYSTEM=1 ;;
  esac
fi
if ((PROFILE_FROM_SYSTEM == 0)); then
  while IFS= read -r state_file; do
    [[ -f "$state_file" ]] || continue
    state_repo="$(jq -r '.repository // empty' "$state_file" 2>/dev/null || true)"
    [[ "$state_repo" == "{repo_ref}" ]] || continue
    candidate="$(jq -r '.profile // empty' "$state_file" 2>/dev/null || true)"
    case "$candidate" in
      "{host_ref}"|"{host_ref}-mango"|"{host_ref}-niri"|"{host_ref}-hyprland"|"{host_ref}-hyprland-caelestia"|"{host_ref}-mango-niri"|"{host_ref}-mango-hyprland"|"{host_ref}-niri-hyprland"|"{host_ref}-all") {shell_var}="$candidate" ;;
    esac
    break
  done < <(find "$HOME/.local/state/nixos-config" -name state.json -type f 2>/dev/null || true)
fi
'''
    target.write_text(text[:block_start] + new + text[block_end:])
'''

patched = source[:start] + replacement + source[end:]
compile(patched, str(source_path), "exec")
exec(compile(patched, str(source_path), "exec"), {"__name__": "__main__", "__file__": str(source_path)})
