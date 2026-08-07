#!/usr/bin/env python3
from __future__ import annotations

import fcntl
import json
import os
import pwd
import re
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import NoReturn, Sequence

EXPECTED_REMOTES = {
    "https://github.com/madebycli/nix-config.git",
    "git@github.com:madebycli/nix-config.git",
}
MODE_INPUTS: dict[str, tuple[str, ...]] = {
    "all": (
        "nixpkgs",
        "home-manager",
        "nix-cachyos-kernel",
        "mango",
        "noctalia",
        "noctalia-greeter",
    ),
    "base": ("nixpkgs", "nix-cachyos-kernel"),
    "packages": ("nixpkgs",),
    "kernel": ("nix-cachyos-kernel",),
    "desktop": ("home-manager", "mango", "noctalia", "noctalia-greeter"),
    "profiles": (),
}
PROFILE_MODES = {"all", "base", "packages", "profiles"}
PROFILE_RE = re.compile(r"^(nyx|aether)(-(mango|niri))?$")
SYSTEM_PROFILE = Path("/nix/var/nix/profiles/system")


class HelperError(RuntimeError):
    pass


@dataclass(frozen=True)
class Caller:
    uid: int
    name: str
    home: Path


def event(kind: str, **payload: object) -> None:
    print(json.dumps({"event": kind, **payload}, ensure_ascii=False), flush=True)


def fail(message: str) -> NoReturn:
    event("operation-failed", error=message)
    raise SystemExit(1)


def caller() -> Caller:
    raw_uid = os.environ.get("PKEXEC_UID")
    if raw_uid is None or not raw_uid.isdigit():
        raise HelperError("PKEXEC_UID is unavailable; run through the desktop Polkit agent")
    entry = pwd.getpwuid(int(raw_uid))
    if entry.pw_uid == 0:
        raise HelperError("root is not a valid desktop caller")
    return Caller(entry.pw_uid, entry.pw_name, Path(entry.pw_dir).resolve())


def executable(name: str) -> str:
    value = shutil.which(name)
    if value is None:
        raise HelperError(f"required program is missing: {name}")
    resolved = str(Path(value).resolve())
    if not (
        resolved.startswith("/nix/store/")
        or resolved.startswith("/run/current-system/")
    ):
        raise HelperError(f"refusing non-Nix executable path: {resolved}")
    return resolved


def safe_env() -> dict[str, str]:
    allowed = ("PATH", "NIX_PATH", "SSL_CERT_FILE", "NIX_SSL_CERT_FILE", "LOCALE_ARCHIVE")
    result = {key: os.environ[key] for key in allowed if key in os.environ}
    result["LANG"] = "C.UTF-8"
    result["LC_ALL"] = "C.UTF-8"
    result["NO_COLOR"] = "1"
    return result


def user_command(who: Caller, args: Sequence[str]) -> list[str]:
    env_program = executable("env")
    runuser = executable("runuser")
    return [
        runuser,
        "-u",
        who.name,
        "--",
        env_program,
        f"HOME={who.home}",
        f"USER={who.name}",
        f"LOGNAME={who.name}",
        f"PATH={os.environ.get('PATH', '')}",
        "NO_COLOR=1",
        *args,
    ]


def capture(args: Sequence[str], *, cwd: Path | None = None) -> str:
    try:
        completed = subprocess.run(
            list(args),
            cwd=cwd,
            env=safe_env(),
            check=True,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            start_new_session=True,
        )
    except (OSError, subprocess.CalledProcessError) as exc:
        if isinstance(exc, subprocess.CalledProcessError):
            detail = (exc.stderr or exc.stdout or "").strip()
        else:
            detail = str(exc)
        raise HelperError(detail or f"command failed: {args[0]}") from exc
    return completed.stdout.strip()


def capture_optional(args: Sequence[str], *, cwd: Path | None = None) -> str:
    try:
        return capture(args, cwd=cwd)
    except HelperError:
        return ""


def stream(args: Sequence[str], *, phase: str, cwd: Path | None = None) -> None:
    event("phase-started", phase=phase)
    try:
        process = subprocess.Popen(
            list(args),
            cwd=cwd,
            env=safe_env(),
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            start_new_session=True,
            bufsize=1,
        )
    except OSError as exc:
        raise HelperError(str(exc)) from exc
    assert process.stdout is not None
    for raw in process.stdout:
        line = raw.rstrip("\n")
        if line:
            event("log", phase=phase, stream="stdout", message=line)
    code = process.wait()
    if code != 0:
        raise HelperError(f"{phase} failed with exit code {code}")
    event("phase-completed", phase=phase)


def validate_repo(raw: str, who: Caller) -> Path:
    repo = Path(raw).expanduser().resolve()
    try:
        repo.relative_to(who.home)
    except ValueError as exc:
        raise HelperError("repository must be inside the caller home directory") from exc
    if not (repo / ".git").is_dir() or not (repo / "flake.nix").is_file():
        raise HelperError("repository is not a complete Nix configuration checkout")
    owner = repo.stat().st_uid
    if owner != who.uid:
        raise HelperError("repository is not owned by the desktop caller")
    git = executable("git")
    remote = capture(user_command(who, [git, "-C", str(repo), "remote", "get-url", "origin"]))
    if remote not in EXPECTED_REMOTES:
        raise HelperError(f"unexpected Git remote: {remote}")
    return repo


def validate_profile(value: str) -> str:
    if PROFILE_RE.fullmatch(value) is None:
        raise HelperError("profile is not in the allowed host/profile set")
    return value


def generation_links() -> list[Path]:
    links = list(Path("/nix/var/nix/profiles").glob("system-*-link"))
    return sorted(links, key=generation_number, reverse=True)


def generation_number(link: Path) -> int:
    match = re.fullmatch(r"system-(\d+)-link", link.name)
    if match is None:
        raise HelperError(f"invalid generation link: {link}")
    return int(match.group(1))


def operation_optimize() -> None:
    before = directory_bytes(Path("/nix/store"))
    stream([executable("nix-store"), "--optimise", "-vv"], phase="optimize-store")
    after = directory_bytes(Path("/nix/store"))
    event("operation-completed", operation="optimize", beforeBytes=before, afterBytes=after)


def directory_bytes(path: Path) -> int:
    output = capture([executable("du"), "-sB1", str(path)])
    token = output.split(maxsplit=1)[0]
    return int(token) if token.isdigit() else 0


def operation_rollback() -> None:
    stream([executable("nixos-rebuild"), "switch", "--rollback"], phase="rollback")
    event("operation-completed", operation="rollback")


def operation_switch(repo_value: str, profile_value: str) -> None:
    who = caller()
    repo = validate_repo(repo_value, who)
    profile = validate_profile(profile_value)
    flake = f"{repo}#{profile}"
    rebuild = executable("nixos-rebuild")
    stream([rebuild, "build", "--flake", flake], phase="build-system")
    stream([rebuild, "switch", "--flake", flake], phase="switch-system")
    event("operation-completed", operation="switch", profile=profile)


def operation_clean(backups_value: str) -> None:
    if not backups_value.isdigit() or not 1 <= int(backups_value) <= 20:
        raise HelperError("backup count must be between 1 and 20")
    backups = int(backups_value)
    links = generation_links()
    if not links:
        raise HelperError("no system generations found")
    current = Path("/run/current-system").resolve()
    boot = SYSTEM_PROFILE.resolve()
    if current != boot:
        raise HelperError("running system and boot default differ")
    current_link = next((link for link in links if link.resolve() == current), None)
    if current_link is None:
        raise HelperError("running generation could not be resolved")
    current_generation = generation_number(current_link)
    latest_generation = generation_number(links[0])
    if current_generation != latest_generation:
        raise HelperError("running generation is not the latest generation")
    remove = [generation_number(link) for link in links[backups + 1 :]]
    event(
        "phase-completed",
        phase="cleanup-preview-verified",
        currentGeneration=current_generation,
        keepBackups=backups,
        deleteGenerations=remove,
    )
    if remove:
        stream(
            [
                executable("nix-env"),
                "--profile",
                str(SYSTEM_PROFILE),
                "--delete-generations",
                *[str(item) for item in remove],
            ],
            phase="delete-generations",
        )
        switch = Path("/run/current-system/bin/switch-to-configuration")
        if not switch.is_file():
            raise HelperError("switch-to-configuration is unavailable")
        stream([str(switch), "boot"], phase="refresh-boot-profile")
        stream([executable("nix"), "store", "gc"], phase="garbage-collect")
    event("operation-completed", operation="clean", deleteGenerations=remove)


def git_relation(who: Caller, repo: Path, branch: str) -> tuple[int, int]:
    git = executable("git")
    output = capture(
        user_command(
            who,
            [git, "-C", str(repo), "rev-list", "--left-right", "--count", f"HEAD...origin/{branch}"],
        )
    )
    left, right = output.split()
    return int(left), int(right)


def operation_refresh(mode: str, repo_value: str, profile_value: str) -> None:
    if mode not in MODE_INPUTS:
        raise HelperError("refresh mode is not allowed")
    who = caller()
    repo = validate_repo(repo_value, who)
    profile = validate_profile(profile_value)
    git = executable("git")
    nix = executable("nix")
    rebuild = executable("nixos-rebuild")

    staged = capture(user_command(who, [git, "-C", str(repo), "diff", "--cached", "--name-only"]))
    if staged:
        raise HelperError("staged Git changes found")
    stream(user_command(who, [git, "-C", str(repo), "fetch", "--prune", "origin"]), phase="fetch-config")
    branch = capture(user_command(who, [git, "-C", str(repo), "branch", "--show-current"]))
    if not branch:
        raise HelperError("no local branch is checked out")
    ahead, behind = git_relation(who, repo, branch)
    if ahead and behind:
        raise HelperError("local and remote histories diverged")
    if behind:
        raise HelperError("GitHub contains newer configuration commits")

    identity_name = capture_optional(user_command(who, [git, "-C", str(repo), "config", "user.name"]))
    identity_email = capture_optional(user_command(who, [git, "-C", str(repo), "config", "user.email"]))
    publish = ahead == 0 and bool(identity_name and identity_email)

    state_dir = who.home / ".local/state/nixos-config/nix-refresh-backups"
    state_dir.mkdir(mode=0o700, parents=True, exist_ok=True)
    os.chown(state_dir, who.uid, pwd.getpwnam(who.name).pw_gid)
    backup = state_dir / f"helper-{os.getpid()}-flake.lock"
    shutil.copy2(repo / "flake.lock", backup)
    backup.chmod(0o600)
    os.chown(backup, who.uid, pwd.getpwnam(who.name).pw_gid)

    system_active = False
    try:
        inputs = MODE_INPUTS[mode]
        if mode != "profiles":
            stream(
                user_command(
                    who,
                    [nix, "flake", "update", *inputs, "--flake", str(repo), "--refresh"],
                ),
                phase="update-lock",
            )
            flake = f"{repo}#{profile}"
            stream([rebuild, "build", "--flake", flake], phase="build-system")
            stream([rebuild, "switch", "--flake", flake], phase="switch-system")
            system_active = True
            marker = Path("/var/lib/nixos-config/fstrim-pending")
            marker.parent.mkdir(mode=0o755, parents=True, exist_ok=True)
            marker.touch(mode=0o644, exist_ok=True)
        if mode in PROFILE_MODES:
            stream(
                user_command(who, [nix, "profile", "upgrade", "--all", "--refresh"]),
                phase="update-profile",
            )

        changed = capture(
            user_command(who, [git, "-C", str(repo), "diff", "--name-only", "--", "flake.lock"])
        )
        if changed and publish:
            stream(user_command(who, [git, "-C", str(repo), "add", "--", "flake.lock"]), phase="stage-lock")
            stream(
                user_command(
                    who,
                    [git, "-C", str(repo), "commit", "-m", f"update({mode}): refresh Flake inputs"],
                ),
                phase="commit-lock",
            )
            stream(user_command(who, [git, "-C", str(repo), "fetch", "--prune", "origin"]), phase="verify-remote")
            push_ahead, push_behind = git_relation(who, repo, branch)
            if push_behind == 0 and push_ahead > 0:
                stream(user_command(who, [git, "-C", str(repo), "push", "origin", branch]), phase="push-lock")
            elif push_behind:
                event("log", phase="push-lock", stream="stderr", message="remote advanced; commit remains local")
    except Exception:
        if not system_active:
            shutil.copy2(backup, repo / "flake.lock")
            os.chown(repo / "flake.lock", who.uid, pwd.getpwnam(who.name).pw_gid)
            event("log", phase="restore-lock", stream="stderr", message="flake.lock restored from backup")
        raise
    finally:
        backup.unlink(missing_ok=True)

    event("operation-completed", operation="refresh", mode=mode, profile=profile)


def dispatch(argv: Sequence[str]) -> None:
    if os.geteuid() != 0:
        raise HelperError("the privileged helper must run as root through pkexec")
    if not argv:
        raise HelperError("operation is required")
    operation = argv[0]
    event("operation-started", operation=operation)
    if operation == "optimize" and len(argv) == 1:
        operation_optimize()
    elif operation == "rollback" and len(argv) == 1:
        operation_rollback()
    elif operation == "clean" and len(argv) == 2:
        operation_clean(argv[1])
    elif operation == "switch" and len(argv) == 3:
        operation_switch(argv[1], argv[2])
    elif operation == "refresh" and len(argv) == 4:
        operation_refresh(argv[1], argv[2], argv[3])
    else:
        raise HelperError("operation or arguments are not allowed")


def main(argv: Sequence[str] | None = None) -> int:
    lock_path = Path("/run/lock/nix-settings-helper.lock")
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    with lock_path.open("w", encoding="utf-8") as lock:
        try:
            fcntl.flock(lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            fail("another privileged Nix Settings operation is running")
        try:
            dispatch(list(sys.argv[1:] if argv is None else argv))
        except HelperError as exc:
            fail(str(exc))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
