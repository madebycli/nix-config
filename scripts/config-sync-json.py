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


def load_backend() -> ModuleType:
    path = Path(__file__).with_name("config-sync.py")
    spec = importlib.util.spec_from_file_location("nix_config_sync_backend", path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load config-sync backend: {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def emit(payload: dict[str, Any]) -> None:
    print(json.dumps(payload, ensure_ascii=False, sort_keys=True))


def status_payload(backend: ModuleType, args: argparse.Namespace) -> dict[str, Any]:
    repo = backend.find_repo(args.repo)
    backend.ensure_remote(repo)
    backend.fetch(repo, args.offline)
    ahead, behind, upstream = backend.relation(repo)
    branch = backend.git(repo, "branch", "--show-current")
    state = backend.load_state(repo)
    local_changes = list(backend.worktree_lines(repo))
    staged_changes = list(backend.staged(repo))

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


def doctor_payload(backend: ModuleType, args: argparse.Namespace) -> dict[str, Any]:
    checks: list[dict[str, Any]] = []
    repo = backend.find_repo(args.repo)

    def check(name: str, callback: Any) -> None:
        try:
            callback()
        except Exception as exc:
            checks.append({"id": name, "ok": False, "detail": str(exc)})
        else:
            checks.append({"id": name, "ok": True, "detail": None})

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
    if not args.offline:
        check("remote-fetch", lambda: backend.fetch(repo, False))
        check(
            "history-relation",
            lambda: (_ for _ in ()).throw(backend.SyncError("Git history diverged"))
            if all(backend.relation(repo)[:2])
            else None,
        )

    return {
        "schemaVersion": 1,
        "repositoryPath": str(repo),
        "ok": all(item["ok"] for item in checks),
        "checks": checks,
        "errors": [item["detail"] for item in checks if not item["ok"]],
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
        payload = {
            "status": status_payload,
            "paths": paths_payload,
            "doctor": doctor_payload,
        }[args.command](backend, args)
    except Exception as exc:
        emit({"schemaVersion": 1, "errors": [str(exc)], "ok": False})
        return 1
    emit(payload)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
