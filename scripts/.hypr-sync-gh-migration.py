#!/usr/bin/env python3
from pathlib import Path


def replace_once(path: str, old: str, new: str) -> None:
    target = Path(path)
    text = target.read_text()
    if old not in text:
        raise SystemExit(f"expected text not found in {path}")
    target.write_text(text.replace(old, new, 1))


replace_once(
    "flake.nix",
    '          homeImports = [ ./modules/home ]\n            ++ nixpkgs.lib.optional (builtins.elem "hyprland" desktops) ./modules/home/hyprland.nix;\n',
    '          homeImports = [ ./modules/home ];\n',
)

replace_once(
    "flake.nix",
    '          coreutils diffutils findutils git gnugrep gnused jq nix python3 rsync util-linux\n',
    '          coreutils diffutils findutils gh git gnugrep gnused jq nix python3 rsync util-linux\n',
)

refresh_old = (
    '    if gh auth status --hostname github.com >/dev/null 2>&1; then\n'
    '      gh auth setup-git --hostname github.com >/dev/null 2>&1 || true\n'
    '      if ! GIT_TERMINAL_PROMPT=0 git -C "$REPO" push origin "$BRANCH"; then\n'
    "        printf 'GitHub push failed; commit remains local.\\n' >&2\n"
    '      fi\n'
    '    else\n'
    "      printf 'GitHub push skipped; authenticate once with: gh auth login --hostname github.com --git-protocol https --web\\n' >&2\n"
    '    fi\n'
)
refresh_new = (
    '    if ! gh auth status --hostname github.com >/dev/null 2>&1; then\n'
    "      printf '\\n==> GitHub authentication required\\n'\n"
    '      gh auth login --hostname github.com --git-protocol https --web\n'
    '    fi\n'
    '    gh auth setup-git --hostname github.com >/dev/null 2>&1\n'
    '    if ! GIT_TERMINAL_PROMPT=0 git -C "$REPO" push origin "$BRANCH"; then\n'
    "      printf 'GitHub push failed; commit remains local.\\n' >&2\n"
    '    fi\n'
)
replace_once("scripts/nix-refresh.sh", refresh_old, refresh_new)

sync_anchor = (
    'def ensure_remote(repo: Path) -> None:\n'
    '    remote = git(repo, "remote", "get-url", "origin", check=False)\n'
    '    if remote and remote not in EXPECTED_REMOTES:\n'
    '        raise SyncError(f"Unerwartetes Git-Remote: {remote}")\n'
)
sync_helper = sync_anchor + (
    '\n\n'
    'def ensure_github_auth(repo: Path) -> None:\n'
    '    status = run(["gh", "auth", "status", "--hostname", "github.com"], cwd=repo, check=False)\n'
    '    if status.returncode != 0:\n'
    '        info("GitHub-Anmeldung wird einmalig eingerichtet")\n'
    '        run(\n'
    '            ["gh", "auth", "login", "--hostname", "github.com", "--git-protocol", "https", "--web"],\n'
    '            cwd=repo,\n'
    '            capture=False,\n'
    '        )\n'
    '    run(["gh", "auth", "setup-git", "--hostname", "github.com"], cwd=repo, capture=False)\n'
)
replace_once("scripts/config-sync.py", sync_anchor, sync_helper)

replace_once(
    "scripts/config-sync.py",
    '    branch = git(repo, "branch", "--show-current")\n    if target is None:\n',
    '    ensure_github_auth(repo)\n    branch = git(repo, "branch", "--show-current")\n    if target is None:\n',
)

Path("modules/home/hyprland.nix").unlink(missing_ok=True)
Path("config/home/.config/hypr/hyprland.conf").unlink(missing_ok=True)
