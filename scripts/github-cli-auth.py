#!/usr/bin/env python3
"""GitHub CLI authentication bridge for config-sync.

The bridge deliberately never prints or reads authentication tokens. GitHub CLI
owns credential storage; Git is configured to ask ``gh`` for HTTPS credentials.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import socket
import subprocess
import sys
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Sequence

REPOSITORY = "madebycli/nix-config"
HTTPS_REMOTE = f"https://github.com/{REPOSITORY}.git"
EXPECTED_REMOTES = {
    HTTPS_REMOTE,
    f"git@github.com:{REPOSITORY}.git",
}
WRITE_PERMISSIONS = {"ADMIN", "MAINTAIN", "WRITE"}


class AuthError(RuntimeError):
    pass


@dataclass(frozen=True)
class AuthStatus:
    gh_installed: bool
    authenticated: bool
    login: str | None
    permission: str | None
    can_push: bool
    remote_url: str | None
    remote_ok: bool
    git_name: str | None
    git_email: str | None
    credential_helper_ready: bool
    error: str | None = None


def run(
    args: Sequence[str],
    *,
    cwd: Path | None = None,
    check: bool = False,
) -> subprocess.CompletedProcess[str]:
    try:
        return subprocess.run(
            list(args),
            cwd=cwd,
            check=check,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=60,
        )
    except FileNotFoundError as exc:
        raise AuthError(f"Required program is missing: {args[0]}") from exc
    except subprocess.TimeoutExpired as exc:
        raise AuthError(f"Command timed out: {' '.join(args)}") from exc
    except subprocess.CalledProcessError as exc:
        detail = (exc.stderr or exc.stdout or "").strip()
        raise AuthError(detail or f"Command failed: {' '.join(args)}") from exc


def git(repo: Path, *args: str, check: bool = False) -> str:
    result = run(["git", *args], cwd=repo, check=check)
    return result.stdout.strip()


def find_repo(explicit: str | None) -> Path:
    candidates: list[Path] = []
    if explicit:
        candidates.append(Path(explicit).expanduser())
    configured = os.environ.get("NIXOS_CONFIG_REPO")
    if configured:
        candidates.append(Path(configured).expanduser())
    current = Path.cwd().resolve()
    candidates.extend([current, *current.parents])
    home = Path.home()
    hostname = socket.gethostname().split(".", 1)[0]
    candidates.extend([home / hostname, home / "nyx", home / "aether"])

    seen: set[Path] = set()
    for candidate in candidates:
        candidate = candidate.resolve()
        if candidate in seen:
            continue
        seen.add(candidate)
        if (candidate / ".git").is_dir() and (candidate / "flake.nix").is_file():
            return candidate
    raise AuthError("NixOS repository not found")


def _gh_value(*args: str) -> str | None:
    result = run(["gh", *args])
    if result.returncode != 0:
        return None
    value = result.stdout.strip()
    return value or None


def _authenticated() -> tuple[bool, str | None]:
    result = run(["gh", "auth", "status", "--hostname", "github.com"])
    if result.returncode != 0:
        detail = (result.stderr or result.stdout).strip()
        return False, detail or "Not signed in to GitHub CLI"
    return True, None


def _permission() -> str | None:
    return _gh_value(
        "repo",
        "view",
        REPOSITORY,
        "--json",
        "viewerPermission",
        "--jq",
        ".viewerPermission",
    )


def _credential_helper_ready() -> bool:
    result = run(["git", "config", "--global", "--get-all", "credential.https://github.com.helper"])
    if result.returncode != 0:
        return False
    return "gh auth git-credential" in result.stdout


def status(repo: Path) -> AuthStatus:
    remote = git(repo, "remote", "get-url", "origin") or None
    name = git(repo, "config", "user.name") or None
    email = git(repo, "config", "user.email") or None
    if shutil.which("gh") is None:
        return AuthStatus(
            gh_installed=False,
            authenticated=False,
            login=None,
            permission=None,
            can_push=False,
            remote_url=remote,
            remote_ok=remote in EXPECTED_REMOTES,
            git_name=name,
            git_email=email,
            credential_helper_ready=False,
            error="GitHub CLI (gh) is not installed",
        )

    authenticated, error = _authenticated()
    login = _gh_value("api", "user", "--jq", ".login") if authenticated else None
    permission = _permission() if authenticated else None
    return AuthStatus(
        gh_installed=True,
        authenticated=authenticated,
        login=login,
        permission=permission,
        can_push=permission in WRITE_PERMISSIONS,
        remote_url=remote,
        remote_ok=remote in EXPECTED_REMOTES,
        git_name=name,
        git_email=email,
        credential_helper_ready=_credential_helper_ready(),
        error=error,
    )


def _configure_identity(repo: Path) -> None:
    current_name = git(repo, "config", "user.name")
    current_email = git(repo, "config", "user.email")
    if current_name and current_email:
        return

    payload = run(["gh", "api", "user"])
    if payload.returncode != 0:
        detail = (payload.stderr or payload.stdout).strip()
        raise AuthError(detail or "Could not read GitHub account details")
    try:
        user = json.loads(payload.stdout)
    except json.JSONDecodeError as exc:
        raise AuthError("GitHub account response was not valid JSON") from exc

    login = str(user.get("login") or "").strip()
    if not login:
        raise AuthError("GitHub account has no login name")
    if not current_name:
        name = str(user.get("name") or login).strip() or login
        run(["git", "config", "--local", "user.name", name], cwd=repo, check=True)
    if not current_email:
        email = str(user.get("email") or "").strip()
        if not email:
            user_id = user.get("id")
            email = f"{user_id}+{login}@users.noreply.github.com" if user_id else f"{login}@users.noreply.github.com"
        run(["git", "config", "--local", "user.email", email], cwd=repo, check=True)


def prepare(repo: Path, *, require_push: bool) -> AuthStatus:
    current = status(repo)
    if not current.gh_installed:
        raise AuthError("GitHub CLI (gh) is required for authenticated synchronization")
    if not current.remote_ok:
        raise AuthError(f"Unexpected Git remote: {current.remote_url or '<missing>'}")
    if not current.authenticated:
        raise AuthError("Not signed in. Open Nix Settings → Config Sync and choose Sign in.")

    # Browser login is intentionally paired with HTTPS. If an older installation
    # still uses the accepted SSH URL, normalize only this known origin.
    if current.remote_url != HTTPS_REMOTE:
        run(["git", "remote", "set-url", "origin", HTTPS_REMOTE], cwd=repo, check=True)

    setup = run(["gh", "auth", "setup-git", "--hostname", "github.com"])
    if setup.returncode != 0:
        detail = (setup.stderr or setup.stdout).strip()
        raise AuthError(detail or "GitHub CLI could not configure the Git credential helper")

    _configure_identity(repo)
    prepared = status(repo)
    if require_push and not prepared.can_push:
        permission = prepared.permission or "UNKNOWN"
        raise AuthError(f"GitHub account {prepared.login or '<unknown>'} cannot push to {REPOSITORY} ({permission})")
    return prepared


def emit(value: AuthStatus) -> None:
    print(json.dumps(asdict(value), ensure_ascii=False, sort_keys=True))


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(prog="github-cli-auth")
    result.add_argument("command", choices=("status", "prepare"))
    result.add_argument("--repo")
    result.add_argument("--require-push", action="store_true")
    result.add_argument("--json", action="store_true")
    return result


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    try:
        repo = find_repo(args.repo)
        value = status(repo) if args.command == "status" else prepare(repo, require_push=args.require_push)
    except AuthError as exc:
        if args.json:
            print(json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False))
        else:
            print(f"GitHub authentication error: {exc}", file=sys.stderr)
        return 1
    if args.json:
        emit(value)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
