#!/usr/bin/env python3
"""Read-only JSON adapter for the existing config-sync implementation."""

from __future__ import annotations

import argparse
import importlib.util
import json
import socket
import sys
from pathlib import Path
from types import ModuleType
from typing import Any


def load_module(filename: str, name: str) -> ModuleType:
    path = Path(__file__).with_name(filename)
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load backend: {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def load_backend() -> ModuleType:
    return load_module("config-sync.py", "nix_config_sync_backend")


def load_auth_backend() -> ModuleType:
    return load_module("github-cli-auth.py", "nix_config_github_auth")


def emit(payload: dict[str, Any]) -> None:
    print(json.dumps(payload, ensure_ascii=False, sort_keys=True))


def github_payload(auth_backend: ModuleType, repo: Path) -> dict[str, Any]:
    value = auth_backend.status(repo)
    return {
        "ghInstalled": bool(value.gh_installed),
        "authenticated": bool(value.authenticated),
        "login": value.login,
        "permission": value.permission,
        "canPush": bool(value.can_push),
        "remoteUrl": value.remote_url,
        "remoteOk": bool(value.remote_ok),
        "gitName": value.git_name,
        "gitEmail": value.git_email,
        "credentialHelperReady": bool(value.credential_helper_ready),
        "error": value.error,
    }


def status_payload(
    backend: ModuleType,
    auth_backend: ModuleType,
    args: argparse.Namespace,
) -> dict[str, Any]:
    repo = backend.find_repo(args.repo)
    backend.ensure_remote(repo)
    backend.fetch(repo, args.offline)
    ahead, behind, upstream = backend.relation(repo)
    branch = backend.git(repo, "branch", "--show-current")
    state = backend.load_state(repo)
    local_changes = list(backend.worktree_lines(repo))
    staged_output = backend.git(repo, "diff", "--cached", "--name-only")
    staged_changes = staged_output.splitlines() if staged_output else []

    changes: dict[str, list[str]] = {
        "local": [],
        "remote": [],
        "same": [],
        "conflicts": [],
    }
    if args.scope != "nixos":
        active, mirror, baseline = backend.manifests(repo)
        classified = backend.classify(active, mirror, baseline)
        changes = {
            "local": list(classified.local),
            "remote": list(classified.remote),
            "same": list(classified.same),
            "conflicts": list(classified.conflicts),
        }

    backups = backend.state_dir(repo) / "backups"
    backup_entries = []
    if backups.is_dir():
        backup_entries = sorted(
            (str(path) for path in backups.iterdir() if path.is_dir()), reverse=True
        )[:20]

    planned_action = "none"
    if changes["conflicts"] or (ahead and behind):
        planned_action = "manual-resolution-required"
    elif behind and (changes["local"] or local_changes):
        planned_action = "safe-sync"
    elif behind:
        planned_action = "download"
    elif ahead or changes["local"] or local_changes:
        planned_action = "upload"

    github = github_payload(auth_backend, repo)
    return {
        "schemaVersion": 1,
        "repositoryPath": str(repo),
        "profile": backend.profile_from_state(repo, None),
        "host": socket.gethostname().split(".", 1)[0],
        "scope": args.scope,
        "branch": branch,
        "upstream": upstream,
        "ahead": ahead,
        "behind": behind,
        "dirty": bool(local_changes or staged_changes),
        "lastSync": state.get("last_sync"),
        "lastSyncedCommit": state.get("last_synced_commit"),
        "localChanges": local_changes,
        "stagedChanges": staged_changes,
        "changes": changes,
        "plannedAction": planned_action,
        "backups": backup_entries,
        "github": github,
        "errors": [],
    }


def paths_payload(backend: ModuleType, args: argparse.Namespace) -> dict[str, Any]:
    repo = backend.find_repo(args.repo)
    roots = [path.as_posix() for path in backend.selected_roots(repo)]
    excludes = list(backend.exclude_patterns(repo))
    checks = []
    for value in roots:
        reason = backend.secret_reason(value)
        checks.append({"path": value, "safe": reason is None, "reason": reason})
    return {
        "schemaVersion": 1,
        "repositoryPath": str(repo),
        "pathsFile": str(repo / backend.PATHS_FILE),
        "excludesFile": str(repo / backend.EXCLUDES_FILE),
        "managedPaths": roots,
        "excludePatterns": excludes,
        "checks": checks,
        "errors": [],
    }


def doctor_payload(
    backend: ModuleType,
    auth_backend: ModuleType,
    args: argparse.Namespace,
) -> dict[str, Any]:
    checks: list[dict[str, Any]] = []
    repo = backend.find_repo(args.repo)

    def check(name: str, callback: Any, *, required: bool = True) -> None:
        try:
            callback()
        except Exception as exc:
            checks.append(
                {
                    "id": name,
                    "ok": False,
                    "required": required,
                    "detail": str(exc),
                }
            )
        else:
            checks.append({"id": name, "ok": True, "required": required, "detail": None})

    check("remote", lambda: backend.ensure_remote(repo))

    def validate_paths() -> None:
        roots = backend.selected_roots(repo)
        patterns = backend.exclude_patterns(repo)
        backend.scan_tree(Path.home(), roots, patterns)
        backend.scan_tree(repo / backend.MIRROR_PREFIX, roots, patterns)

    check("paths-secrets-symlinks", validate_paths)
    check(
        "git-index",
        lambda: (_ for _ in ()).throw(backend.SyncError("Git index is not empty"))
        if backend.staged(repo)
        else None,
    )
    check("sync-state", lambda: backend.load_state(repo))

    auth = auth_backend.status(repo)
    check(
        "github-cli",
        lambda: (_ for _ in ()).throw(auth_backend.AuthError("GitHub CLI (gh) is not installed"))
        if not auth.gh_installed
        else None,
        required=False,
    )
    check(
        "github-login",
        lambda: (_ for _ in ()).throw(
            auth_backend.AuthError(auth.error or "Not signed in to GitHub CLI")
        )
        if not auth.authenticated
        else None,
        required=False,
    )
    check(
        "github-write-permission",
        lambda: (_ for _ in ()).throw(
            auth_backend.AuthError(
                f"GitHub account cannot push to {auth_backend.REPOSITORY} ({auth.permission or 'UNKNOWN'})"
            )
        )
        if auth.authenticated and not auth.can_push
        else None,
        required=False,
    )

    if not args.offline:
        check("remote-fetch", lambda: backend.fetch(repo, False))
        check(
            "history-relation",
            lambda: (_ for _ in ()).throw(backend.SyncError("Git history diverged"))
            if all(backend.relation(repo)[:2])
            else None,
        )

    required_checks = [item for item in checks if item["required"]]
    return {
        "schemaVersion": 1,
        "repositoryPath": str(repo),
        "ok": all(item["ok"] for item in required_checks),
        "checks": checks,
        "github": github_payload(auth_backend, repo),
        "errors": [
            item["detail"]
            for item in required_checks
            if not item["ok"] and item["detail"] is not None
        ],
    }


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(prog="config-sync-json")
    result.add_argument("command", choices=("status", "paths", "doctor"))
    result.add_argument("--repo")
    result.add_argument("--offline", action="store_true")
    result.add_argument("--scope", choices=("all", "nixos", "dotfiles"), default="all")
    return result


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    try:
        backend = load_backend()
        auth_backend = load_auth_backend()
        payload = {
            "status": lambda: status_payload(backend, auth_backend, args),
            "paths": lambda: paths_payload(backend, args),
            "doctor": lambda: doctor_payload(backend, auth_backend, args),
        }[args.command]()
    except Exception as exc:
        emit({"schemaVersion": 1, "errors": [str(exc)], "ok": False})
        return 1
    emit(payload)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
