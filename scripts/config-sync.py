#!/usr/bin/env python3
"""Manuelle, konfliktarme Synchronisation für NixOS-Repo und Dotconfigs."""

from __future__ import annotations

import argparse
import datetime as dt
import fcntl
import fnmatch
import hashlib
import json
import os
import shutil
import socket
import stat
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Mapping, Sequence

EXPECTED_REMOTES = {
    "https://github.com/xnixjoyer/nixos-config.git",
    "git@github.com:xnixjoyer/nixos-config.git",
}
MIRROR_PREFIX = Path("config/home")
PATHS_FILE = Path("sync/paths.conf")
EXCLUDES_FILE = Path("sync/excludes.conf")
STATE_VERSION = 1


class SyncError(RuntimeError):
    pass


@dataclass(frozen=True)
class ChangeSet:
    local: tuple[str, ...]
    remote: tuple[str, ...]
    same: tuple[str, ...]
    conflicts: tuple[str, ...]


def run(
    args: Sequence[str],
    *,
    cwd: Path | None = None,
    check: bool = True,
    capture: bool = True,
) -> subprocess.CompletedProcess[str]:
    try:
        return subprocess.run(
            list(args),
            cwd=cwd,
            check=check,
            text=True,
            stdout=subprocess.PIPE if capture else None,
            stderr=subprocess.PIPE if capture else None,
        )
    except FileNotFoundError as exc:
        raise SyncError(f"Benötigtes Programm fehlt: {args[0]}") from exc
    except subprocess.CalledProcessError as exc:
        detail = (exc.stderr or exc.stdout or "").strip()
        command = " ".join(args)
        raise SyncError(f"Befehl fehlgeschlagen: {command}\n{detail}") from exc


def git(repo: Path, *args: str, check: bool = True) -> str:
    return run(["git", *args], cwd=repo, check=check).stdout.strip()


def now_stamp() -> str:
    return dt.datetime.now().astimezone().strftime("%Y-%m-%d_%H-%M-%S")


def info(message: str) -> None:
    print(f"\n==> {message}")


def confirm(message: str, assume_yes: bool) -> bool:
    if assume_yes:
        return True
    answer = input(f"\n{message} [j/N] ").strip().lower()
    return answer in {"j", "ja", "y", "yes"}


def find_repo(explicit: str | None) -> Path:
    candidates: list[Path] = []
    if explicit:
        candidates.append(Path(explicit).expanduser())
    if os.environ.get("NIXOS_CONFIG_REPO"):
        candidates.append(Path(os.environ["NIXOS_CONFIG_REPO"]).expanduser())

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

    raise SyncError(
        "NixOS-Repository nicht gefunden. Im Repository starten oder "
        "--repo /pfad/zum/repository angeben."
    )


def state_dir(repo: Path) -> Path:
    digest = hashlib.sha256(str(repo).encode()).hexdigest()[:12]
    return Path.home() / ".local/state/nixos-config" / f"{repo.name}-{digest}"


def state_path(repo: Path) -> Path:
    return state_dir(repo) / "state.json"


def load_state(repo: Path) -> dict:
    path = state_path(repo)
    if not path.exists():
        return {"version": STATE_VERSION, "files": {}}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise SyncError(f"Ungültiger Synchronisationszustand: {path}") from exc
    if data.get("version") != STATE_VERSION or not isinstance(data.get("files"), dict):
        raise SyncError(f"Nicht unterstützter Synchronisationszustand: {path}")
    return data


def save_state(repo: Path, files: Mapping[str, str], profile: str | None) -> None:
    directory = state_dir(repo)
    directory.mkdir(parents=True, exist_ok=True)
    payload = {
        "version": STATE_VERSION,
        "repository": str(repo),
        "host": socket.gethostname().split(".", 1)[0],
        "profile": profile,
        "last_synced_commit": git(repo, "rev-parse", "HEAD"),
        "last_sync": dt.datetime.now().astimezone().isoformat(timespec="seconds"),
        "files": dict(sorted(files.items())),
    }
    temporary = directory / ".state.json.tmp"
    temporary.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    os.replace(temporary, state_path(repo))


def read_config_lines(path: Path) -> list[str]:
    if not path.is_file():
        raise SyncError(f"Konfigurationsdatei fehlt: {path}")
    result: list[str] = []
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        result.append(line)
    return result


def selected_roots(repo: Path) -> tuple[Path, ...]:
    roots: list[Path] = []
    for value in read_config_lines(repo / PATHS_FILE):
        path = Path(value)
        if path.is_absolute() or ".." in path.parts:
            raise SyncError(f"Unsicherer Pfad in {PATHS_FILE}: {value}")
        roots.append(path)
    if not roots:
        raise SyncError(f"Keine Pfade in {PATHS_FILE} eingetragen.")
    return tuple(roots)


def exclude_patterns(repo: Path) -> tuple[str, ...]:
    return tuple(read_config_lines(repo / EXCLUDES_FILE))


def is_excluded(relative: str, patterns: Iterable[str]) -> bool:
    return any(fnmatch.fnmatch(relative, pattern) for pattern in patterns)


def secret_reason(relative: str) -> str | None:
    path = Path(relative)
    lowered = relative.lower()
    name = path.name.lower()
    parts = {part.lower() for part in path.parts}

    if name == ".env" or name.startswith(".env."):
        return ".env-Datei"
    if path.suffix.lower() in {".pem", ".key", ".p12", ".pfx"}:
        return "Schlüssel- oder Zertifikatsdatei"
    if name in {"id_rsa", "id_ed25519", "known_hosts", "cookies", "cookies.sqlite", "login data"}:
        return "Zugangsdaten- oder Browserdatei"
    if {"sessions", "session", "local storage"} & parts:
        return "Sitzungs- oder Browserzustand"
    if any(token in lowered for token in ("token", "secret", "password", "credentials")):
        return "mögliche Zugangsdaten im Dateinamen"
    return None


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def scan_tree(base: Path, roots: Sequence[Path], patterns: Sequence[str]) -> dict[str, str]:
    manifest: dict[str, str] = {}
    for root in roots:
        source = base / root
        if not source.exists():
            continue
        if source.is_symlink():
            raise SyncError(f"Symbolischer Link nicht erlaubt: {source}")
        if not source.is_dir():
            raise SyncError(f"Ausgewählter Pfad ist kein Verzeichnis: {source}")

        for directory, dirnames, filenames in os.walk(source, followlinks=False):
            directory_path = Path(directory)
            for dirname in list(dirnames):
                candidate = directory_path / dirname
                relative = candidate.relative_to(base).as_posix()
                if candidate.is_symlink():
                    raise SyncError(f"Symbolischer Link nicht erlaubt: {candidate}")
                if is_excluded(relative + "/", patterns) or is_excluded(relative, patterns):
                    dirnames.remove(dirname)

            for filename in filenames:
                candidate = directory_path / filename
                relative = candidate.relative_to(base).as_posix()
                if is_excluded(relative, patterns):
                    continue
                mode = candidate.lstat().st_mode
                if stat.S_ISLNK(mode):
                    raise SyncError(f"Symbolischer Link nicht erlaubt: {candidate}")
                if not stat.S_ISREG(mode):
                    raise SyncError(f"Nur normale Dateien sind erlaubt: {candidate}")
                reason = secret_reason(relative)
                if reason:
                    raise SyncError(f"Blockierte Datei ({reason}): {candidate}")
                manifest[relative] = sha256_file(candidate)
    return manifest


def manifests(repo: Path) -> tuple[dict[str, str], dict[str, str], dict[str, str]]:
    roots = selected_roots(repo)
    patterns = exclude_patterns(repo)
    active = scan_tree(Path.home(), roots, patterns)
    mirror = scan_tree(repo / MIRROR_PREFIX, roots, patterns)
    baseline = load_state(repo).get("files", {})
    return active, mirror, baseline


def classify(
    active: Mapping[str, str], mirror: Mapping[str, str], baseline: Mapping[str, str]
) -> ChangeSet:
    local: list[str] = []
    remote: list[str] = []
    same: list[str] = []
    conflicts: list[str] = []

    for path in sorted(set(active) | set(mirror) | set(baseline)):
        local_value = active.get(path)
        remote_value = mirror.get(path)
        base_value = baseline.get(path)

        if local_value == remote_value:
            same.append(path)
            continue

        local_changed = local_value != base_value
        remote_changed = remote_value != base_value

        if local_changed and remote_changed:
            conflicts.append(path)
        elif local_changed:
            local.append(path)
        elif remote_changed:
            remote.append(path)
        else:
            conflicts.append(path)

    return ChangeSet(tuple(local), tuple(remote), tuple(same), tuple(conflicts))


def format_path_change(path: str, active: Mapping[str, str], mirror: Mapping[str, str]) -> str:
    if path not in active:
        return f"D {path} (lokal gelöscht)"
    if path not in mirror:
        return f"A {path} (nur lokal)"
    return f"M {path}"


def print_changes(changes: ChangeSet, active: Mapping[str, str], mirror: Mapping[str, str]) -> None:
    print("\nDotconfigs:")
    for path in changes.local:
        print(f"  L {format_path_change(path, active, mirror)}")
    for path in changes.remote:
        print(f"  R {path}")
    for path in changes.conflicts:
        print(f"  ! {path}")
    print(
        f"  = {len(changes.same)} gleich, {len(changes.local)} lokal, "
        f"{len(changes.remote)} Repository, {len(changes.conflicts)} Konflikte"
    )


def upstream(repo: Path) -> str | None:
    result = git(repo, "rev-parse", "--abbrev-ref", "--symbolic-full-name", "@{u}", check=False)
    if result:
        return result
    branch = git(repo, "branch", "--show-current")
    candidate = f"origin/{branch}"
    exists = git(repo, "show-ref", "--verify", f"refs/remotes/{candidate}", check=False)
    return candidate if exists else None


def fetch(repo: Path, offline: bool) -> None:
    if offline:
        return
    remote = git(repo, "remote", "get-url", "origin", check=False)
    if remote:
        info("GitHub-Stand wird geprüft")
        run(["git", "fetch", "--prune", "origin"], cwd=repo, capture=False)


def relation(repo: Path) -> tuple[int, int, str | None]:
    target = upstream(repo)
    if not target:
        return 0, 0, None
    output = git(repo, "rev-list", "--left-right", "--count", f"HEAD...{target}")
    left, right = output.split()
    return int(left), int(right), target


def worktree_lines(repo: Path) -> list[str]:
    output = git(repo, "status", "--short", "--untracked-files=all")
    return output.splitlines() if output else []


def staged(repo: Path) -> bool:
    result = run(["git", "diff", "--cached", "--quiet"], cwd=repo, check=False)
    return result.returncode != 0


def ensure_remote(repo: Path) -> None:
    remote = git(repo, "remote", "get-url", "origin", check=False)
    if remote and remote not in EXPECTED_REMOTES:
        raise SyncError(f"Unerwartetes Git-Remote: {remote}")


def changed_repo_paths(repo: Path) -> list[str]:
    paths: set[str] = set()
    for command in (
        ["git", "diff", "--name-only", "-z"],
        ["git", "diff", "--cached", "--name-only", "-z"],
        ["git", "ls-files", "--others", "--exclude-standard", "-z"],
    ):
        output = run(command, cwd=repo).stdout
        paths.update(item for item in output.split("\0") if item)
    return sorted(paths)


def validate_repo_changes(repo: Path, paths: Sequence[str]) -> None:
    blocked: list[str] = []
    for relative in paths:
        path = repo / relative
        reason = secret_reason(relative)
        if reason:
            blocked.append(f"{relative}: {reason}")
        if path.exists() and path.is_symlink():
            blocked.append(f"{relative}: symbolischer Link")
    if blocked:
        raise SyncError("Unsichere Dateien im Git-Stand:\n  " + "\n  ".join(blocked))


def paths_for_scope(paths: Sequence[str], scope: str) -> list[str]:
    if scope == "all":
        return list(paths)
    is_dot = lambda value: value == str(MIRROR_PREFIX) or value.startswith(f"{MIRROR_PREFIX.as_posix()}/")
    if scope == "dotfiles":
        return [path for path in paths if is_dot(path)]
    return [path for path in paths if not is_dot(path)]


def copy_local_to_mirror(repo: Path, paths: Iterable[str]) -> None:
    for relative in paths:
        source = Path.home() / relative
        target = repo / MIRROR_PREFIX / relative
        if source.exists():
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, target)
        else:
            target.unlink(missing_ok=True)
            remove_empty_parents(target.parent, repo / MIRROR_PREFIX)


def remove_empty_parents(path: Path, stop: Path) -> None:
    current = path
    while current != stop and current.is_dir():
        try:
            current.rmdir()
        except OSError:
            break
        current = current.parent


def backup_file(repo: Path, relative: str, backup_root: Path) -> None:
    source = Path.home() / relative
    if not source.exists():
        return
    target = backup_root / "home" / relative
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, target)


def apply_mirror_to_local(
    repo: Path, paths: Iterable[str], backup_root: Path, *, assume_yes: bool
) -> None:
    paths = tuple(paths)
    if not paths:
        return
    print("\nFolgende lokale Dateien werden aus dem Repository aktualisiert:")
    for relative in paths:
        print(f"  {relative}")
    if not confirm("Backups anlegen und diese Änderungen übernehmen?", assume_yes):
        raise SyncError("Übernahme abgebrochen.")

    for relative in paths:
        source = repo / MIRROR_PREFIX / relative
        target = Path.home() / relative
        if target.exists() and (not source.exists() or sha256_file(target) != sha256_file(source)):
            backup_file(repo, relative, backup_root)
        if source.exists():
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, target)
        else:
            target.unlink(missing_ok=True)
            remove_empty_parents(target.parent, Path.home())


def selective_baseline(
    old: Mapping[str, str],
    active: Mapping[str, str],
    mirror: Mapping[str, str],
    changes: ChangeSet,
) -> dict[str, str]:
    result: dict[str, str] = {}
    local_set = set(changes.local)
    for path in sorted(set(old) | set(active) | set(mirror)):
        if path in local_set:
            if path in old:
                result[path] = old[path]
        elif active.get(path) == mirror.get(path) and path in active:
            result[path] = active[path]
    return result


def show_git(repo: Path) -> None:
    lines = worktree_lines(repo)
    print("\nGit-Arbeitsbaum:")
    if lines:
        for line in lines:
            print(f"  {line}")
    else:
        print("  sauber")


def show_relation(repo: Path) -> tuple[int, int, str | None]:
    ahead, behind, target = relation(repo)
    print("\nGit-Historie:")
    if target is None:
        print("  Kein Upstream konfiguriert.")
    else:
        print(f"  Upstream: {target}")
        print(f"  Lokal voraus: {ahead}, lokal zurück: {behind}")
    return ahead, behind, target


def commit_and_push(
    repo: Path,
    *,
    scope: str,
    message: str | None,
    no_commit: bool,
    offline: bool,
    assume_yes: bool,
) -> bool:
    all_paths = changed_repo_paths(repo)
    scoped = paths_for_scope(all_paths, scope)
    if not scoped:
        print("\nKeine Repository-Änderungen im gewählten Bereich.")
        return False

    validate_repo_changes(repo, scoped)
    print("\nÄnderungen für Git:")
    for path in scoped:
        print(f"  {path}")
    run(["git", "--no-pager", "diff", "--stat", "--", *scoped], cwd=repo, check=False, capture=False)

    if no_commit:
        print("\nÄnderungen wurden nur in den Repository-Spiegel kopiert; kein Commit.")
        return True

    if staged(repo):
        raise SyncError("Es existieren bereits vorgemerkte Änderungen. Automatischer Commit abgebrochen.")
    if not confirm("Diese Dateien stagen und committen?", assume_yes):
        raise SyncError("Commit abgebrochen.")

    run(["git", "add", "-A", "--", *scoped], cwd=repo, capture=False)
    run(["git", "--no-pager", "diff", "--cached", "--stat"], cwd=repo, capture=False)

    commit_message = message
    if not commit_message:
        commit_message = input("Commit-Nachricht (leer = Standard): ").strip()
    if not commit_message:
        commit_message = (
            f"config-sync({socket.gethostname().split('.', 1)[0]}): "
            f"{dt.datetime.now().astimezone().strftime('%Y-%m-%d %H:%M')}"
        )

    run(["git", "commit", "-m", commit_message], cwd=repo, capture=False)
    if offline:
        print("\nOffline-Modus: Commit erstellt, kein Push.")
        return True

    fetch(repo, offline=False)
    ahead, behind, target = relation(repo)
    if behind:
        raise SyncError(
            "Remote wurde während des Vorgangs geändert. Commit bleibt lokal; "
            "es wurde nicht gepusht."
        )
    branch = git(repo, "branch", "--show-current")
    if target is None:
        run(["git", "push", "-u", "origin", branch], cwd=repo, capture=False)
    else:
        run(["git", "push", "origin", branch], cwd=repo, capture=False)
    return True


def changed_between(repo: Path, old: str, new: str) -> list[str]:
    if old == new:
        return []
    output = git(repo, "diff", "--name-only", f"{old}..{new}")
    return output.splitlines() if output else []


def needs_system_apply(paths: Iterable[str]) -> bool:
    ignored_prefixes = ("config/home/", "docs/", ".github/")
    ignored_files = {"README.md", "CHANGES-FROM-ORIGINALS.md", "VALIDATION.md", "ORIGINAL-DIFF.patch"}
    return any(path not in ignored_files and not path.startswith(ignored_prefixes) for path in paths)


def profile_from_state(repo: Path, explicit: str | None) -> str:
    if explicit:
        return explicit
    state = load_state(repo)
    if state.get("profile"):
        return str(state["profile"])
    return socket.gethostname().split(".", 1)[0]


def apply_system(repo: Path, profile: str, assume_yes: bool) -> None:
    if not confirm(f"NixOS-Profil '{profile}' jetzt bauen?", assume_yes):
        print("\nSystem-Build übersprungen.")
        return
    info(f"NixOS wird zuerst gebaut: {profile}")
    run(["sudo", "nixos-rebuild", "build", "--flake", f"{repo}#{profile}"], capture=False)
    if confirm("Build erfolgreich. Jetzt auf die neue Generation wechseln?", assume_yes):
        run(["sudo", "nixos-rebuild", "switch", "--flake", f"{repo}#{profile}"], capture=False)
    else:
        print(f"\nKein Switch. Ergebnis: {repo}/result")


def fast_forward(repo: Path, offline: bool) -> tuple[str, list[str]]:
    old_head = git(repo, "rev-parse", "HEAD")
    fetch(repo, offline)
    ahead, behind, target = relation(repo)
    if ahead and behind:
        raise SyncError("Lokale und entfernte Git-Historie sind divergiert. Manuelle Lösung erforderlich.")
    if behind:
        if worktree_lines(repo):
            raise SyncError(
                "Remote ist neuer, aber das Repository enthält lokale Änderungen. "
                "Zuerst pushen/committen oder Änderungen manuell sichern."
            )
        if target is None:
            raise SyncError("Kein Upstream für Fast-Forward vorhanden.")
        info(f"Repository wird per Fast-Forward auf {target} aktualisiert")
        run(["git", "merge", "--ff-only", target], cwd=repo, capture=False)
    new_head = git(repo, "rev-parse", "HEAD")
    return new_head, changed_between(repo, old_head, new_head)


def command_status(args: argparse.Namespace) -> None:
    repo = find_repo(args.repo)
    ensure_remote(repo)
    fetch(repo, args.offline)
    print(f"Repository: {repo}")
    show_git(repo)
    show_relation(repo)
    if args.scope != "nixos":
        active, mirror, baseline = manifests(repo)
        print_changes(classify(active, mirror, baseline), active, mirror)
    state = load_state(repo)
    if state.get("last_sync"):
        print(f"\nLetzter erfolgreicher Dotconfig-Sync: {state['last_sync']}")


def command_push(args: argparse.Namespace) -> None:
    repo = find_repo(args.repo)
    ensure_remote(repo)
    if staged(repo):
        raise SyncError("Bereits vorgemerkte Änderungen gefunden. Nichts wird automatisch übernommen.")
    fetch(repo, args.offline)
    ahead, behind, _ = relation(repo)
    if behind:
        raise SyncError("GitHub enthält neuere Commits. Zuerst 'config-sync pull' oder 'sync' ausführen.")
    if ahead and behind:
        raise SyncError("Git-Historie divergiert.")

    if args.scope != "nixos":
        active, mirror, baseline = manifests(repo)
        changes = classify(active, mirror, baseline)
        print_changes(changes, active, mirror)
        if changes.conflicts:
            raise SyncError("Dotconfig-Konflikte erkannt. Keine Datei wurde überschrieben.")
        if changes.remote:
            raise SyncError("Repository-Dotconfigs sind neuer. Zuerst pull oder sync ausführen.")
        copy_local_to_mirror(repo, changes.local)

    changed = commit_and_push(
        repo,
        scope=args.scope,
        message=args.message,
        no_commit=args.no_commit,
        offline=args.offline,
        assume_yes=args.yes,
    )
    if changed and not args.no_commit and args.scope != "nixos":
        active, mirror, _ = manifests(repo)
        if active != mirror:
            raise SyncError("Interner Fehler: Home und Repository-Spiegel sind nach Push nicht identisch.")
        save_state(repo, active, profile_from_state(repo, args.profile))


def command_pull(args: argparse.Namespace) -> None:
    repo = find_repo(args.repo)
    ensure_remote(repo)
    if staged(repo):
        raise SyncError("Bereits vorgemerkte Änderungen gefunden. Pull abgebrochen.")
    if worktree_lines(repo):
        raise SyncError(
            "Das Repository enthält lokale Änderungen. Für einen sicheren Pull "
            "zuerst 'config-sync push' oder 'config-sync sync' verwenden."
        )
    _, pulled_paths = fast_forward(repo, args.offline)

    if args.scope != "nixos":
        active, mirror, baseline = manifests(repo)
        changes = classify(active, mirror, baseline)
        print_changes(changes, active, mirror)
        if changes.conflicts:
            raise SyncError("Lokale und entfernte Dotconfigs wurden gleichzeitig geändert.")
        backup_root = state_dir(repo) / "backups" / now_stamp()
        apply_mirror_to_local(repo, changes.remote, backup_root, assume_yes=args.yes)
        new_active, new_mirror, _ = manifests(repo)
        new_baseline = selective_baseline(baseline, new_active, new_mirror, changes)
        save_state(repo, new_baseline, profile_from_state(repo, args.profile))
        if changes.remote:
            print(f"\nSelektive Backups: {backup_root}")

    if args.scope != "dotfiles" and not args.no_apply and needs_system_apply(pulled_paths):
        apply_system(repo, profile_from_state(repo, args.profile), args.yes)
    elif pulled_paths:
        print("\nRepository wurde aktualisiert; Systemaktivierung wurde übersprungen.")


def command_sync(args: argparse.Namespace) -> None:
    repo = find_repo(args.repo)
    ensure_remote(repo)
    if staged(repo):
        raise SyncError("Bereits vorgemerkte Änderungen gefunden. Sync abgebrochen.")

    _, pulled_paths = fast_forward(repo, args.offline)
    if args.scope != "nixos":
        active, mirror, baseline = manifests(repo)
        changes = classify(active, mirror, baseline)
        print_changes(changes, active, mirror)
        if changes.conflicts:
            raise SyncError("Konflikte erkannt. Keine automatische Gewinnerwahl nach Datum.")

        backup_root = state_dir(repo) / "backups" / now_stamp()
        apply_mirror_to_local(repo, changes.remote, backup_root, assume_yes=args.yes)
        copy_local_to_mirror(repo, changes.local)

    commit_and_push(
        repo,
        scope=args.scope,
        message=args.message,
        no_commit=args.no_commit,
        offline=args.offline,
        assume_yes=args.yes,
    )

    if args.scope != "nixos":
        active, mirror, _ = manifests(repo)
        if active != mirror:
            raise SyncError("Home und Repository-Spiegel sind nach Sync nicht identisch.")
        save_state(repo, active, profile_from_state(repo, args.profile))

    if args.scope != "dotfiles" and not args.no_apply and needs_system_apply(pulled_paths):
        apply_system(repo, profile_from_state(repo, args.profile), args.yes)


def command_init(args: argparse.Namespace) -> None:
    repo = find_repo(args.repo)
    ensure_remote(repo)
    if worktree_lines(repo):
        print("\nHinweis: Repository enthält lokale Änderungen; Initialisierung verwendet diesen lokalen Stand.")
    else:
        fast_forward(repo, args.offline)
    if state_path(repo).exists() and not args.force:
        raise SyncError("Synchronisationszustand existiert bereits. Für Neuinitialisierung --force verwenden.")
    roots = selected_roots(repo)
    patterns = exclude_patterns(repo)
    active = scan_tree(Path.home(), roots, patterns)
    mirror = scan_tree(repo / MIRROR_PREFIX, roots, patterns)

    if args.from_repo:
        paths = sorted(mirror)
        backup_root = state_dir(repo) / "backups" / now_stamp()
        apply_mirror_to_local(repo, paths, backup_root, assume_yes=args.yes)
        active = scan_tree(Path.home(), roots, patterns)
        common = {path: value for path, value in active.items() if mirror.get(path) == value}
        save_state(repo, common, args.profile or socket.gethostname().split(".", 1)[0])
        print(f"\nSynchronisation initialisiert. Backups bei Bedarf: {backup_root}")
    else:
        common = {path: value for path, value in active.items() if mirror.get(path) == value}
        save_state(repo, common, args.profile or socket.gethostname().split(".", 1)[0])
        print("\nSynchronisationszustand ohne Kopiervorgang initialisiert.")


def command_history(args: argparse.Namespace) -> None:
    repo = find_repo(args.repo)
    path_args = [args.path] if args.path else ["config/home", "hosts", "modules", "scripts", "sync", "flake.nix", "flake.lock"]
    run(
        [
            "git",
            "--no-pager",
            "log",
            "--date=iso-local",
            "--pretty=format:%C(auto)%h %ad %an%n  %s",
            "--stat",
            "--",
            *path_args,
        ],
        cwd=repo,
        capture=False,
    )


def command_doctor(args: argparse.Namespace) -> None:
    repo = find_repo(args.repo)
    failures: list[str] = []
    print(f"Repository: {repo}")

    try:
        ensure_remote(repo)
        print("[OK] Git-Remote")
    except SyncError as exc:
        failures.append(str(exc))

    try:
        roots = selected_roots(repo)
        patterns = exclude_patterns(repo)
        scan_tree(Path.home(), roots, patterns)
        scan_tree(repo / MIRROR_PREFIX, roots, patterns)
        print("[OK] Pfade, Secrets und Symlinks")
    except SyncError as exc:
        failures.append(str(exc))

    if staged(repo):
        failures.append("Git-Index enthält bereits vorgemerkte Änderungen.")
    else:
        print("[OK] Git-Index leer")

    if state_path(repo).exists():
        try:
            state = load_state(repo)
            commit = state.get("last_synced_commit")
            if commit:
                git(repo, "cat-file", "-e", f"{commit}^{{commit}}")
            print("[OK] Synchronisationszustand")
        except SyncError as exc:
            failures.append(str(exc))
    else:
        print("[HINWEIS] Noch kein Synchronisationszustand; 'config-sync init' ausführen.")

    if not args.offline:
        try:
            fetch(repo, False)
            ahead, behind, _ = relation(repo)
            if ahead and behind:
                failures.append("Git-Historie ist divergiert.")
            else:
                print(f"[OK] Git-Historie (voraus {ahead}, zurück {behind})")
        except SyncError as exc:
            failures.append(str(exc))

    if failures:
        print("\nProbleme:")
        for failure in failures:
            print(f"  - {failure}")
        raise SyncError(f"Doctor fand {len(failures)} Problem(e).")
    print("\nDoctor: keine blockierenden Probleme gefunden.")


def parser() -> argparse.ArgumentParser:
    main = argparse.ArgumentParser(prog="config-sync")
    main.add_argument("--repo", help="Pfad zum NixOS-Repository")
    main.add_argument("--offline", action="store_true", help="Keine Netzwerkoperation")
    main.add_argument("--yes", "-y", action="store_true", help="Bestätigungen automatisch bejahen")
    main.add_argument("--profile", help="NixOS-Flake-Profil, z. B. nyx-niri")
    main.add_argument(
        "--scope",
        choices=("all", "nixos", "dotfiles"),
        default="all",
        help="all (Standard), nixos oder dotfiles",
    )
    commands = main.add_subparsers(dest="command", required=True)

    commands.add_parser("status", help="Nur Zustand anzeigen")

    push = commands.add_parser("push", help="Lokale Änderungen committen und pushen")
    push.add_argument("--message", "-m")
    push.add_argument("--no-commit", action="store_true")

    pull = commands.add_parser("pull", help="Fast-Forward-Pull und sichere Übernahme")
    pull.add_argument("--no-apply", action="store_true", help="Kein NixOS-Build/Switch")

    sync = commands.add_parser("sync", help="Sicherer kombinierter Pull/Push")
    sync.add_argument("--message", "-m")
    sync.add_argument("--no-commit", action="store_true")
    sync.add_argument("--no-apply", action="store_true")

    init = commands.add_parser("init", help="Lokalen Synchronisationszustand anlegen")
    init.add_argument("--from-repo", action="store_true", help="Repository nach HOME kopieren")
    init.add_argument("--force", action="store_true")

    history = commands.add_parser("history", help="Git-Historie anzeigen")
    history.add_argument("path", nargs="?")

    commands.add_parser("doctor", help="Einrichtung prüfen")
    return main


def normalize_argv(argv: Sequence[str]) -> list[str]:
    """Erlaubt globale Optionen vor oder nach dem Unterbefehl."""
    value_options = {"--repo", "--profile", "--scope"}
    flag_options = {"--offline", "--yes", "-y"}
    global_args: list[str] = []
    remaining: list[str] = []
    index = 0
    while index < len(argv):
        token = argv[index]
        if token in value_options:
            if index + 1 >= len(argv):
                raise SyncError(f"{token} benötigt einen Wert.")
            global_args.extend([token, argv[index + 1]])
            index += 2
        elif token in flag_options:
            global_args.append(token)
            index += 1
        else:
            remaining.append(token)
            index += 1
    return global_args + remaining


def main() -> int:
    try:
        args = parser().parse_args(normalize_argv(sys.argv[1:]))
    except SyncError as exc:
        print(f"\nFehler: {exc}", file=sys.stderr)
        return 2
    repo: Path | None = None
    lock_handle = None
    try:
        if args.command not in {"history", "status"}:
            repo = find_repo(args.repo)
            directory = state_dir(repo)
            directory.mkdir(parents=True, exist_ok=True)
            lock_handle = (directory / "lock").open("w")
            try:
                fcntl.flock(lock_handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError as exc:
                raise SyncError("Ein anderer config-sync-Prozess läuft bereits.") from exc

        {
            "status": command_status,
            "push": command_push,
            "pull": command_pull,
            "sync": command_sync,
            "init": command_init,
            "history": command_history,
            "doctor": command_doctor,
        }[args.command](args)
        return 0
    except (SyncError, KeyboardInterrupt) as exc:
        print(f"\nFehler: {exc}", file=sys.stderr)
        return 1
    finally:
        if lock_handle is not None:
            lock_handle.close()


if __name__ == "__main__":
    raise SystemExit(main())
