#!/usr/bin/env python3
"""nx - update, switch and housekeeping for this NixOS configuration.

Design rules:
  * `nx check` only asks upstreams for their newest revision (git ls-remote,
    in parallel). It never evaluates, downloads or builds anything.
  * Nothing is activated before a build succeeded and you confirmed it.
  * Updating restores flake.lock whenever the build fails or you decline.
  * Every read command offers --json for tools such as the Noctalia plugin.
"""

import argparse
import concurrent.futures
import json
import os
import re
import shlex
import subprocess
import sys
import tempfile
import time
from datetime import datetime
from pathlib import Path

CONF = Path(os.environ.get("NX_CONF", "/etc/nixctl.conf"))
CACHE_DIR = Path(os.environ.get("XDG_CACHE_HOME", Path.home() / ".cache")) / "nx"
SYSTEM_PROFILE = Path("/nix/var/nix/profiles/system")
GROUPS = {
    "base": ["nixpkgs", "nix-cachyos-kernel"],
    "desktop": ["home-manager", "mango", "caelestia-shell"],
    "apps": ["microvm"],
}
CACHE_TTL = 600  # seconds a `check` result counts as fresh for `status`

TTY = sys.stdout.isatty()


def paint(code, text):
    return f"\033[{code}m{text}\033[0m" if TTY else text


def die(message, code=1):
    print(f"nx: {message}", file=sys.stderr)
    sys.exit(code)


# --------------------------------------------------------------------------- config


def load_conf():
    values = {}
    try:
        for line in CONF.read_text().splitlines():
            if "=" in line:
                key, value = line.split("=", 1)
                parts = shlex.split(value)
                values[key.strip()] = parts[0] if parts else ""
    except OSError:
        die(f"cannot read {CONF} (is my.features rebuilt yet?)")
    if not values.get("REPO") or not values.get("HOST"):
        die(f"{CONF} must define REPO and HOST")
    return Path(values["REPO"]), values["HOST"]


def run(cmd, check=True, capture=False, timeout=None, cwd=None):
    result = subprocess.run(
        cmd, check=False, text=True, timeout=timeout, cwd=cwd,
        stdout=subprocess.PIPE if capture else None,
        stderr=subprocess.PIPE if capture else None,
    )
    if check and result.returncode != 0:
        detail = (result.stderr or "").strip().splitlines()[-1:] if capture else []
        die(f"command failed ({result.returncode}): {' '.join(map(str, cmd))} {' '.join(detail)}")
    return result


def confirm(question, assume_yes):
    if assume_yes:
        return True
    if not sys.stdin.isatty():
        die("confirmation needed but stdin is not a terminal; pass --yes")
    return input(f"{question} [y/N] ").strip().lower().startswith("y")


# --------------------------------------------------------------------------- flake.lock


def resolve_node(lock, edge, seen=()):
    """Follow `follows` paths to the node an input finally points to."""
    if isinstance(edge, str):
        return edge
    node = lock["root"]
    for name in edge:
        if (node, name) in seen:
            raise ValueError("cyclic follows path")
        seen = seen + ((node, name),)
        node = resolve_node(lock, lock["nodes"][node]["inputs"][name], seen)
    return node


def lock_inputs(lock):
    root = lock["nodes"][lock["root"]]
    rows = []
    for name, edge in sorted(root.get("inputs", {}).items()):
        follows = isinstance(edge, list)
        node = lock["nodes"][resolve_node(lock, edge)]
        rows.append({
            "name": name,
            "follows": follows,
            "locked": node.get("locked", {}),
            "original": node.get("original", {}),
        })
    return rows


def remote_of(original):
    """(url, ref) of the upstream to compare against, or None if pinned/unsupported."""
    if original.get("rev"):
        return None  # an explicit revision is deliberate, never "outdated"
    kind, ref = original.get("type"), original.get("ref") or "HEAD"
    if kind == "github":
        url = f"https://github.com/{original['owner']}/{original['repo']}.git"
    elif kind == "gitlab":
        url = f"https://gitlab.com/{original['owner']}/{original['repo']}.git"
    elif kind == "sourcehut":
        url = f"https://git.sr.ht/{original['owner']}/{original['repo']}"
    elif kind == "git":
        url = original.get("url", "").removeprefix("git+")
        if not url.startswith(("https://", "ssh://", "git@")):
            return None
    else:
        return None
    return url, ref


def git_ls_remote(url, ref, timeout=10):
    """Newest commit of `ref` at `url`; raises RuntimeError when unreachable."""
    refs = ["HEAD"] if ref == "HEAD" else [f"refs/heads/{ref}", f"refs/tags/{ref}^{{}}", f"refs/tags/{ref}"]
    try:
        out = subprocess.run(
            ["git", "-c", "protocol.version=2", "ls-remote", "--", url, *refs],
            capture_output=True, text=True, timeout=timeout, check=False,
            env={**os.environ, "GIT_TERMINAL_PROMPT": "0"},
        )
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError("timeout") from exc
    lines = [line.split() for line in out.stdout.splitlines() if line.strip()]
    if out.returncode != 0 or not lines:
        raise RuntimeError(out.stderr.strip().splitlines()[-1] if out.stderr.strip() else "ref not found")
    peeled = next((parts[0] for parts in lines if parts[1].endswith("^{}")), None)
    return peeled or lines[0][0]


def check_rows(rows, ls_remote=git_ls_remote, offline=False, workers=12):
    """Annotate rows with status: update | current | follows | pinned | unreachable | offline."""

    def probe(row):
        row = dict(row)
        row["revision"] = row["locked"].get("rev", "")
        destination = None if row.get("follows") else remote_of(row["original"])
        if row.get("follows"):
            row["status"] = "follows"
        elif destination is None:
            row["status"] = "pinned"
        elif offline:
            row["status"] = "offline"
        else:
            try:
                row["upstream"] = ls_remote(*destination)
                row["status"] = "update" if row["upstream"] != row["revision"] else "current"
            except RuntimeError as exc:
                row["status"], row["error"] = "unreachable", str(exc)
        return row

    with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as pool:
        return list(pool.map(probe, rows))


def profile_rows():
    """Packages installed with `nix profile` that come from a Git-hosted flake."""
    result = subprocess.run(["nix", "profile", "list", "--json"], capture_output=True, text=True, check=False)
    if result.returncode != 0:
        return []
    elements = json.loads(result.stdout or "{}").get("elements", {})
    items = elements.items() if isinstance(elements, dict) else enumerate(elements)
    rows = []
    for name, element in items:
        original = element.get("originalUrl") or ""
        match = re.match(r"^github:([^/]+)/([^/?#]+)(?:/([^?#]+))?", original)
        rev = re.search(r"/([0-9a-f]{40})(?:\?|$|#)", element.get("url") or "")
        if not match:
            continue
        owner, repo, ref = match.groups()
        rows.append({
            "name": str(name), "follows": False, "kind": "profile",
            "locked": {"rev": rev.group(1) if rev else "", "lastModified": 0},
            "original": {"type": "github", "owner": owner, "repo": repo, **({"ref": ref} if ref else {})},
        })
    return rows


# --------------------------------------------------------------------------- generations


def realpath(path):
    try:
        return os.path.realpath(path)
    except OSError:
        return ""


def read_text(path):
    try:
        return Path(path).read_text().strip()
    except OSError:
        return ""


def list_generations(profile_dir=Path("/nix/var/nix/profiles"), selected=None, running=None, booted=None):
    selected = selected or realpath(SYSTEM_PROFILE)
    running = running or realpath("/run/current-system")
    booted = booted or realpath("/run/booted-system")
    rows = []
    for link in profile_dir.glob("system-*-link"):
        match = re.fullmatch(r"system-(\d+)-link", link.name)
        if not match:
            continue
        target = realpath(link)
        kernel = Path(realpath(link / "kernel")).parent.name
        rows.append({
            "number": int(match.group(1)),
            "date": datetime.fromtimestamp(link.lstat().st_mtime).strftime("%Y-%m-%d %H:%M"),
            "version": read_text(link / "nixos-version"),
            "kernel": re.sub(r"^[a-z0-9]{32}-", "", kernel),
            "path": target,
            "selected": target == selected,
            "running": target == running,
            "booted": target == booted,
        })
    return sorted(rows, key=lambda row: row["number"], reverse=True)


def select_deletions(generations, keep):
    """Numbers to delete: keep the newest keep+1 generations and anything selected/running/booted."""
    newest = {row["number"] for row in generations[: keep + 1]}
    protected = {row["number"] for row in generations if row["selected"] or row["running"] or row["booted"]}
    return sorted(row["number"] for row in generations if row["number"] not in newest | protected)


def reboot_needed():
    if not os.path.exists("/run/booted-system"):
        return False
    for part in ("kernel", "initrd", "kernel-modules"):
        if realpath(f"/run/booted-system/{part}") != realpath(f"/run/current-system/{part}"):
            return True
    return False


# --------------------------------------------------------------------------- helpers


def load_lock(repo):
    try:
        return json.loads((repo / "flake.lock").read_text())
    except (OSError, ValueError) as exc:
        die(f"cannot read {repo}/flake.lock: {exc}")


def human_age(timestamp):
    if not timestamp:
        return "-"
    days = int((time.time() - timestamp) / 86400)
    return "today" if days < 1 else f"{days} d ago" if days < 60 else f"{days // 30} mo ago"


def git(repo, *args, check=True):
    return run(["git", "-C", str(repo), *args], check=check, capture=True)


def require_no_conflicts(repo):
    paths = git(repo, "diff", "--name-only", "--diff-filter=U", "-z").stdout.strip("\0")
    if paths:
        die("unresolved Git conflicts: " + ", ".join(paths.split("\0")) +
            "; resolve them before continuing (local changes are not discarded)")


def save_local_lock(repo, text):
    directory = Path(git(repo, "rev-parse", "--git-path", "nx/lock-backups").stdout.strip())
    if not directory.is_absolute():
        directory = repo / directory
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"{time.time_ns()}.lock"
    path.write_text(text)
    print(f"Local lock backup: {path}")
    return path


def reconcile_local_lock(repo, text, backup):
    try:
        result = run(["nix", "flake", "lock", "--flake", str(repo)], check=False)
    except BaseException:
        (repo / "flake.lock").write_text(text)
        raise
    if result.returncode != 0:
        (repo / "flake.lock").write_text(text)
        die(f"code was pulled, but Nix could not reconcile the local lock; original restored, backup: {backup}. "
            "Retry with nx update; nothing was activated")
    print("Local input versions preserved; changed input declarations reconciled by Nix. No commit or push.")


def require_git_identity(repo):
    for identity in ("GIT_AUTHOR_IDENT", "GIT_COMMITTER_IDENT"):
        if git(repo, "var", identity, check=False).returncode != 0:
            die("Git identity is required only for --commit/--push; configure user.name and user.email "
                "or run nx update without those options. Nothing was updated or activated")


def toplevel_attr(repo, host):
    return f"{repo}#nixosConfigurations.{host}.config.system.build.toplevel"


def build_system(repo, host):
    print(paint("1", f"==> Building {host}"))
    result = subprocess.run(
        ["nix", "build", "--no-link", "--print-out-paths", toplevel_attr(repo, host)],
        stdout=subprocess.PIPE, text=True, check=False)
    if result.returncode != 0 or not result.stdout.strip():
        return None
    return result.stdout.strip().splitlines()[-1]


def show_diff(path):
    print(paint("1", "\n==> Changes compared to the running system"))
    run(["nix", "store", "diff-closures", "/run/current-system", path], check=False)


def activate(path, mode):
    if mode in ("switch", "boot"):
        run(["sudo", "nix-env", "-p", str(SYSTEM_PROFILE), "--set", path])
    run(["sudo", f"{path}/bin/switch-to-configuration", mode])
    run(["sudo", "install", "-d", "-m", "0755", "/var/lib/nixos-config"], check=False)
    run(["sudo", "touch", "/var/lib/nixos-config/fstrim-pending"], check=False)
    if reboot_needed():
        print(paint("33", "A reboot is needed to use the new kernel/initrd."))


def untracked_warning(repo):
    out = git(repo, "status", "--porcelain", "--untracked-files=all", check=False).stdout
    fresh = [line[3:] for line in out.splitlines() if line.startswith("??") and line.endswith(".nix")]
    if fresh:
        print(paint("33", "Untracked .nix files are invisible to the flake until `git add`: " + ", ".join(fresh[:5])))


# --------------------------------------------------------------------------- commands


def cmd_check(args):
    repo, _host = load_conf()
    started = time.time()
    rows = lock_inputs(load_lock(repo))
    if args.profiles:
        rows += profile_rows()
    result = check_rows(rows, offline=args.offline)
    summary = {
        "checked": int(time.time()),
        "seconds": round(time.time() - started, 1),
        "updates": [r["name"] for r in result if r["status"] == "update"],
        "unreachable": [r["name"] for r in result if r["status"] == "unreachable"],
        "rows": [
            {k: r.get(k) for k in ("name", "kind", "status", "revision", "upstream", "error")}
            | {"age_days": int((time.time() - r["locked"].get("lastModified", 0)) / 86400) if r["locked"].get("lastModified") else None}
            for r in result
        ],
    }
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    (CACHE_DIR / "check.json").write_text(json.dumps(summary))
    if args.json:
        print(json.dumps(summary, indent=2))
        return 0
    colors = {"update": "33", "current": "32", "unreachable": "31", "follows": "2", "pinned": "2", "offline": "2"}
    for row in result:
        if row["status"] in ("follows",) and not args.all:
            continue
        label = {"update": "update available", "current": "up to date"}.get(row["status"], row["status"])
        extra = f"  ({row.get('error')})" if row.get("error") else ""
        print(f"{row['name']:<22} {paint(colors.get(row['status'], '0'), f'{label:<17}')} locked {human_age(row['locked'].get('lastModified'))}{extra}")
    print()
    if summary["updates"]:
        print(f"{len(summary['updates'])} update(s) in {summary['seconds']}s: {', '.join(summary['updates'])}")
        print("Apply them with: nx update")
    else:
        print(f"Everything is current ({summary['seconds']}s).")
    return 0


def cmd_status(args):
    repo, host = load_conf()
    generations = list_generations()
    current = next((g for g in generations if g["running"]), None)
    branch = git(repo, "branch", "--show-current", check=False).stdout.strip()
    dirty = len([line for line in git(repo, "status", "--porcelain", check=False).stdout.splitlines() if line.strip()])
    counts = git(repo, "rev-list", "--left-right", "--count", f"HEAD...origin/{branch}", check=False).stdout.split()
    ahead, behind = (int(counts[0]), int(counts[1])) if len(counts) == 2 else (None, None)
    features = []
    try:
        text = (repo / "hosts" / host / "features.nix").read_text()
        features = re.findall(r"my\.features\.([A-Za-z0-9_-]+)\.enable\s*=\s*true;", text)
    except OSError:
        pass
    cached = None
    try:
        cached = json.loads((CACHE_DIR / "check.json").read_text())
    except (OSError, ValueError):
        pass
    disk = os.statvfs("/nix")
    data = {
        "host": host, "repo": str(repo), "branch": branch, "dirty_files": dirty,
        "ahead": ahead, "behind": behind,
        "generation": current["number"] if current else None,
        "generation_date": current["date"] if current else None,
        "generations": len(generations),
        "reboot_needed": reboot_needed(),
        "features": features,
        "disk_free_gb": round(disk.f_bavail * disk.f_frsize / 1e9, 1),
        "updates": cached["updates"] if cached else None,
        "updates_checked": cached["checked"] if cached else None,
    }
    if args.json:
        print(json.dumps(data, indent=2))
        return 0
    generation = f"generation {data['generation']} ({data['generation_date']}), " if current else ""
    print(f"{paint('1', host)}  {generation}{data['generations']} generations, {data['disk_free_gb']} GB free")
    if data["reboot_needed"]:
        print(paint("33", "reboot needed (kernel or initrd changed)"))
    sync = "" if ahead is None else f", {ahead} ahead / {behind} behind origin"
    print(f"repo      {repo} [{branch}]{sync}{', ' + str(dirty) + ' changed file(s)' if dirty else ''}")
    print(f"features  {', '.join(features) or '-'}")
    if cached:
        age = int((time.time() - cached["checked"]) / 60)
        ups = ", ".join(cached["updates"]) or "none"
        print(f"updates   {ups}  (checked {age} min ago; run `nx check`)")
    else:
        print("updates   not checked yet (run `nx check`)")
    return 0


def cmd_pull(args):
    repo, _host = load_conf()
    require_no_conflicts(repo)
    branch = git(repo, "branch", "--show-current").stdout.strip()
    if not branch:
        die("no branch checked out")
    git(repo, "fetch", "origin", branch)
    ahead, behind = map(int, git(repo, "rev-list", "--left-right", "--count", f"HEAD...origin/{branch}").stdout.split())
    if ahead and behind:
        die(f"local and remote diverged ({ahead} ahead, {behind} behind); resolve in {repo}")
    if not behind:
        print(f"Already up to date with origin/{branch}.")
        return 0
    local_text = None
    backup = None
    if git(repo, "status", "--porcelain", "--", "flake.lock").stdout.strip():
        # The lock is generated data with locally chosen revisions, not a text
        # document to merge. Keep it out of Git's autostash and let Nix reconcile
        # changed declarations while retaining unchanged local input versions.
        load_lock(repo)
        local_text = (repo / "flake.lock").read_text()
        backup = save_local_lock(repo, local_text)
    print(git(repo, "log", "--oneline", f"HEAD..origin/{branch}").stdout.rstrip())
    try:
        if local_text is not None:
            git(repo, "restore", "--source=HEAD", "--staged", "--worktree", "--", "flake.lock")
        # Merge exactly the fetched ref so another fetch cannot race the checks.
        result = run(["git", "-C", str(repo), "merge", "--ff-only", "--autostash", f"origin/{branch}"], check=False)
    finally:
        if local_text is not None:
            (repo / "flake.lock").write_text(local_text)
    # Git may report success even when applying its autostash left conflicts.
    require_no_conflicts(repo)
    if result.returncode != 0:
        die("fast-forward failed; local lock restored, nothing was activated")
    if local_text is not None:
        reconcile_local_lock(repo, local_text, backup)
    return 0


def cmd_switch(args):
    repo, host = load_conf()
    require_no_conflicts(repo)
    untracked_warning(repo)
    path = build_system(repo, host)
    if not path:
        die("build failed; nothing was changed")
    show_diff(path)
    if args.mode == "build":
        print(f"\nBuilt only: {path}")
        return 0
    if not confirm(f"\nActivate ({args.mode})?", args.yes):
        print("Not activated.")
        return 0
    activate(path, args.mode)
    return 0


def lock_summary(old, new):
    old_map = {r["name"]: r["locked"].get("rev", "")[:8] for r in lock_inputs(old)}
    lines = []
    for row in lock_inputs(new):
        before, after = old_map.get(row["name"], ""), row["locked"].get("rev", "")[:8]
        if before != after:
            lines.append(f"  {row['name']:<22} {before or '-'} -> {after or '-'}")
    return lines


def cmd_update(args):
    repo, host = load_conf()
    require_no_conflicts(repo)
    if args.no_commit and (args.commit or args.push):
        die("--no-commit cannot be combined with --commit or --push")
    commit_lock = (args.commit or args.push) and not args.build
    lock_path = repo / "flake.lock"
    old_text = lock_path.read_text()
    lock = json.loads(old_text)
    names = {r["name"] for r in lock_inputs(lock) if not r["follows"]}

    unknown = [t for t in args.targets if t not in GROUPS and t not in names and t != "all"]
    if unknown:
        die(f"unknown input or group: {', '.join(unknown)} (inputs: {', '.join(sorted(names))}; groups: {', '.join(GROUPS)}, all)")

    profile_outdated = []
    if not args.targets:
        wanted = sorted(names)
        rows = check_rows(profile_rows())
        profile_outdated = [r["name"] for r in rows if r["status"] == "update" and r.get("kind") == "profile"]
    elif "all" in args.targets:
        wanted = sorted(names)
    else:
        wanted = []
        for target in args.targets:
            wanted += GROUPS[target] if target in GROUPS else [target]
        wanted = [n for n in dict.fromkeys(wanted) if n in names]
    if args.profiles and not profile_outdated:
        profile_outdated = [r["name"] for r in profile_rows()]

    if not wanted and not profile_outdated:
        print("Everything is current.")
        return 0
    if wanted:
        print("Updating inputs: " + ", ".join(wanted))
    if profile_outdated:
        print("Updating profile packages: " + ", ".join(profile_outdated))

    if wanted and commit_lock:
        require_git_identity(repo)
    untracked_warning(repo)

    def restore():
        lock_path.write_text(old_text)

    if wanted:
        update = subprocess.run(["nix", "flake", "update", *wanted, "--flake", str(repo)], check=False)
        if update.returncode != 0:
            restore()
            die("flake update failed; flake.lock restored")
        for line in lock_summary(lock, json.loads(lock_path.read_text())):
            print(line)
    path = build_system(repo, host)
    if not path:
        restore()
        die("build failed; flake.lock restored, nothing was changed")
    show_diff(path)
    if args.build:
        restore()
        print("\nBuild check only; flake.lock restored.")
        return 0
    if not confirm("\nActivate this update?", args.yes):
        restore()
        print("Not activated; flake.lock restored.")
        return 0
    activate(path, "boot" if args.boot else "switch")
    if profile_outdated:
        run(["nix", "profile", "upgrade", "--all", "--refresh"], check=False)
    if wanted and commit_lock:
        git(repo, "commit", "-q", "-m", "flake.lock: update " + ", ".join(wanted), "--", "flake.lock")
        print("Committed flake.lock" + (" and pushing" if args.push else " (not pushed; use --push)"))
        if args.push:
            run(["git", "-C", str(repo), "push", "origin", "HEAD"])
    elif wanted:
        print("Updated flake.lock locally; no Git commit or GitHub login required.")
    return 0


def cmd_gen(args):
    generations = list_generations()
    if args.action == "list":
        shown = generations[: args.last] if args.last else generations
        if args.json:
            print(json.dumps(shown, indent=2))
            return 0
        for g in shown:
            flags = "".join(f for f, on in (("*", g["selected"]), ("r", g["running"]), ("b", g["booted"])) if on)
            print(f"{g['number']:>4} {g['date']}  {g['version'][:28]:<28} {g['kernel'][:22]:<22} {flags}")
        print("\n* next boot   r running   b booted")
        return 0
    if args.action == "diff":
        by_number = {g["number"]: g for g in generations}
        first = by_number.get(args.a)
        second = by_number.get(args.b) if args.b else next((g for g in generations if g["running"]), None)
        if not first or not second:
            die("unknown generation number")
        run(["nix", "store", "diff-closures", first["path"], second["path"]])
        return 0
    return 0


def cmd_rollback(args):
    if not confirm("Switch back to the previous generation?", args.yes):
        return 0
    run(["sudo", "nixos-rebuild", "switch", "--rollback"])
    return 0


def cmd_clean(args):
    generations = list_generations()
    doomed = select_deletions(generations, args.keep)
    print(f"Keeping the newest {args.keep + 1} generations plus selected, running and booted ones.")
    print("Delete: " + (", ".join(map(str, doomed)) or "nothing"))
    if args.dry_run:
        return 0
    if doomed and confirm("Delete these generations?", args.yes):
        run(["sudo", "nix-env", "-p", str(SYSTEM_PROFILE), "--delete-generations", *map(str, doomed)])
    if confirm("Free the Nix store now (garbage collection)?", args.yes):
        run(["sudo", "nix", "store", "gc"])
    return 0


def cmd_optimise(_args):
    run(["sudo", "nix", "store", "optimise"])
    return 0


# --------------------------------------------------------------------------- cli


def build_parser():
    parser = argparse.ArgumentParser(prog="nx", description="Update, switch and clean this NixOS configuration.")
    sub = parser.add_subparsers(dest="command", metavar="COMMAND")

    p = sub.add_parser("status", help="host, generation, repository and cached update state (offline)")
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=cmd_status)

    p = sub.add_parser("check", help="which inputs have updates? (fast: git ls-remote only)")
    p.add_argument("--json", action="store_true")
    p.add_argument("--offline", action="store_true", help="only read the lock file")
    p.add_argument("--profiles", action="store_true", help="include `nix profile` packages")
    p.add_argument("--all", action="store_true", help="also list inputs that follow another input")
    p.set_defaults(func=cmd_check)

    p = sub.add_parser("pull", help="fetch the repository, fast-forward only")
    p.set_defaults(func=cmd_pull)

    p = sub.add_parser("switch", help="build this host, show the diff, activate after confirmation")
    p.add_argument("--build", dest="mode", action="store_const", const="build", help="build and show the diff only")
    p.add_argument("--boot", dest="mode", action="store_const", const="boot", help="activate on next boot")
    p.add_argument("--test", dest="mode", action="store_const", const="test", help="activate without a boot entry")
    p.add_argument("-y", "--yes", action="store_true")
    p.set_defaults(func=cmd_switch, mode="switch")

    p = sub.add_parser("update", help="update the local lock (default: all inputs), build, confirm, switch")
    p.add_argument("targets", nargs="*", metavar="TARGET", help="input names, groups (base, desktop, apps) or `all`")
    p.add_argument("--profiles", action="store_true", help="also upgrade `nix profile` packages")
    p.add_argument("--build", action="store_true", help="build only, restore flake.lock afterwards")
    p.add_argument("--boot", action="store_true", help="activate on next boot")
    p.add_argument("--commit", action="store_true", help="explicitly commit flake.lock after activation")
    p.add_argument("--no-commit", action="store_true", help="leave flake.lock local (default; compatibility option)")
    p.add_argument("--push", action="store_true", help="explicitly commit and push flake.lock after activation")
    p.add_argument("-y", "--yes", action="store_true")
    p.set_defaults(func=cmd_update)

    p = sub.add_parser("gen", help="list or compare system generations")
    p.add_argument("action", nargs="?", choices=["list", "diff"], default="list")
    p.add_argument("a", nargs="?", type=int, help="generation for `diff`")
    p.add_argument("b", nargs="?", type=int, help="second generation (default: running)")
    p.add_argument("--last", type=int, metavar="N")
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=cmd_gen)

    p = sub.add_parser("rollback", help="switch to the previous generation")
    p.add_argument("-y", "--yes", action="store_true")
    p.set_defaults(func=cmd_rollback)

    p = sub.add_parser("clean", help="delete old generations and free the store")
    p.add_argument("keep", nargs="?", type=int, default=5, help="rollback generations to keep (default 5)")
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("-y", "--yes", action="store_true")
    p.set_defaults(func=cmd_clean)

    p = sub.add_parser("optimise", help="deduplicate identical files in the store")
    p.set_defaults(func=cmd_optimise)
    return parser


def main(argv=None):
    parser = build_parser()
    args = parser.parse_args(argv)
    if not args.command:
        parser.print_help()
        return 0
    if args.command == "gen" and args.action == "diff" and args.a is None:
        die("usage: nx gen diff A [B]")
    return args.func(args)


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        sys.exit(130)
