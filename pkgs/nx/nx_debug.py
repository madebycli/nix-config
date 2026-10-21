"""Bounded, local-first diagnostics for nx. Python standard library only.

No activation, builds, evaluation, repairs, sudo or automatic uploads. Commands
are explicit argument lists; export is the only intentional persistent write.
"""

import ipaddress
import json
import os
import re
import selectors
import shlex
import shutil
import signal
import socket
import subprocess
import sys
import time
import urllib.parse
from datetime import datetime, timezone
from pathlib import Path

SECTIONS = {
    "system": "OS, kernel, uptime, memory, disk space and pressure",
    "nix": "Nix version, effective client settings and daemon state",
    "cache": "substituters, signatures and optional HTTP cache probes",
    "repo": "nx configuration, Git state, lock inputs and feature switches",
    "profiles": "user packages, profile history and system generations",
    "boot": "running/booted/selected system, kernel and boot space",
    "services": "failed system/user units and selected service details",
    "hardware": "CPU, graphics, drivers, disks and audio",
    "network": "link and DNS status (no connectivity requests)",
    "desktop": "session, compositors, shells and desktop portals",
    "logs": "bounded system/user warning journals and Nix daemon journal",
    "build": "local derivation, output metadata and saved build log (--store-path)",
}
DEFAULT_SECTIONS = tuple(k for k in SECTIONS if k != "build")
SETTING_KEYS = {
    "substitute", "substituters", "extra-substituters", "trusted-substituters",
    "trusted-public-keys", "require-sigs", "fallback", "sandbox", "sandbox-fallback",
    "max-jobs", "cores", "builders-use-substitutes", "experimental-features",
    "extra-experimental-features", "connect-timeout", "stalled-download-timeout",
    "download-attempts", "narinfo-cache-negative-ttl", "narinfo-cache-positive-ttl",
    "allowed-users", "trusted-users", "auto-optimise-store", "keep-outputs",
    "keep-derivations", "build-users-group", "store", "system", "builders",
}
# Builder URLs can contain credentials or command arguments, so only record
# whether remote builders have been configured.
MAX_FILE = 256 * 1024
STORE_PATH = re.compile(r"/nix/store/[0-9abcdfghijklmnpqrsvwxyz]{32}-[^/\s]+\Z")


def add_parser(sub):
    p = sub.add_parser("debug", help="detailed, read-only diagnostics, logs and support reports")
    p.add_argument("sections", nargs="*", metavar="SECTION", help="selected sections; default: all except build")
    p.add_argument("--list", action="store_true", help="list diagnostic sections")
    p.add_argument("--full", action="store_true", help="more hardware, service and journal detail")
    p.add_argument("--json", action="store_true", help="structured, versioned report")
    p.add_argument("--output", metavar="FILE", help="also save report to a new file (mode 0600)")
    p.add_argument("--repo", metavar="PATH", help="repository override; no /etc/nixctl.conf required")
    p.add_argument("--host", metavar="NAME", help="host for reading feature switches, without evaluation")
    p.add_argument("--profile", metavar="PATH", help="inspect a specific Nix user profile")
    p.add_argument("--unit", action="append", default=[], metavar="UNIT", help="also inspect a system unit (repeatable)")
    p.add_argument("--user-unit", action="append", default=[], metavar="UNIT", help="also inspect a user unit (repeatable)")
    p.add_argument("--store-path", metavar="PATH", help="local /nix/store path or .drv; includes build diagnostics")
    p.add_argument("--probe-cache", action="store_true", help="explicitly send HEAD requests to configured HTTP(S) caches")
    p.add_argument("--boot", type=int, default=0, metavar="N", help="journal boot offset, e.g. -1 for previous boot")
    p.add_argument("--lines", type=int, default=None, metavar="N", help="journal lines per query (1..2000; default 80, full 400)")
    p.add_argument("--timeout", type=float, default=8, metavar="SEC", help="per-command timeout (0.1..60; default 8)")
    p.add_argument("--budget", type=float, default=90, metavar="SEC", help="total collection budget (1..600; default 90)")
    p.add_argument("--max-bytes", type=int, default=65536, metavar="N", help="stdout/stderr limit each (1024..1048576)")
    p.add_argument("--strict", action="store_true", help="exit 1 for findings or incomplete checks; default report exit 0")
    p.set_defaults(func=command)


class Redactor:
    """Best-effort sharing hygiene; reports must still be reviewed before sharing."""

    def __init__(self):
        self.identities = []
        home = str(Path.home())
        if home not in ("/", "/root"):
            self.identities.append((home, "<home>"))
        for key in ("USER", "LOGNAME", "HOSTNAME"):
            value = os.environ.get(key, "")
            if len(value) > 2 and value not in ("root", "nixos"):
                self.identities.append((value, "<user>" if key != "HOSTNAME" else "<hostname>"))
        hostname = socket.gethostname()
        if len(hostname) > 2:
            self.identities.append((hostname, "<hostname>"))

    def text(self, value):
        s = str(value)
        s = re.sub(r"\x1b\[[0-?]*[ -/]*[@-~]", "", s)
        s = re.sub(r"[\x00-\x08\x0b-\x1f\x7f]", "", s)
        s = re.sub(r"(?i)((?:https?|ssh|git\+https?|git\+ssh|ftp)://)[^\s/@]+(?::[^\s/@]*)?@", r"\1<credentials>@", s)
        s = re.sub(r"(?i)([?&](?:token|access_token|auth|password|secret|key)=)[^\s&#\"']+", r"\1<redacted>", s)
        s = re.sub(r"(?i)((?:access[-_]?tokens?|password|passwd|secret|authorization|api[-_]?key)\s*[:=]\s*)[^\n]+", r"\1<redacted>", s)
        s = re.sub(r"\b(?:gh[pousr]_[A-Za-z0-9_]+|github_pat_[A-Za-z0-9_]+)\b", "<token>", s)
        s = re.sub(r"\b[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}\b", "<email>", s)
        s = re.sub(r"\b(?:[0-9a-fA-F]{2}:){5}[0-9a-fA-F]{2}\b", "<mac>", s)
        def hide_ip(match):
            try:
                addr = ipaddress.ip_address(match.group())
                return match.group() if addr.is_loopback or addr.is_unspecified else "<ip>"
            except ValueError:
                return match.group()
        s = re.sub(r"(?<![\w.])(?:\d{1,3}\.){3}\d{1,3}(?![\w.])", hide_ip, s)
        s = re.sub(r"(?<![\w:])(?:[0-9a-fA-F]{0,4}:){2,}[0-9a-fA-F:.%]+", hide_ip, s)
        for value, replacement in self.identities:
            s = s.replace(value, replacement) if "/" in value else re.sub(r"(?<![\w-])" + re.escape(value) + r"(?![\w-])", replacement, s)
        return s

    def data(self, value):
        if isinstance(value, dict):
            return {self.text(k): self.data(v) for k, v in value.items()}
        if isinstance(value, (list, tuple)):
            return [self.data(v) for v in value]
        return self.text(value) if isinstance(value, (str, Path)) else value


class Collector:
    def __init__(self, args):
        self.args = args
        self.deadline = time.monotonic() + args.budget
        self.sections = {}
        self.findings = []
        self.settings = None
        self.repo = None
        self.host = None

    def finding(self, severity, section, message, next_step=None):
        self.findings.append({"severity": severity, "section": section, "message": message, "next_step": next_step})

    def add(self, section, label, status="ok", **fields):
        row = {"label": label, "status": status, **fields}
        self.sections.setdefault(section, []).append(row)
        return row

    def file(self, section, path, label=None):
        try:
            with open(path, "rb") as stream:
                data = stream.read(MAX_FILE + 1)
            return self.add(section, label or str(path), "truncated" if len(data) > MAX_FILE else "ok",
                            output=data[:MAX_FILE].decode("utf-8", "replace"))
        except OSError as exc:
            return self.add(section, label or str(path), "unavailable", detail=str(exc))

    def run(self, section, label, argv, transform=None, cwd=None, ok_codes=(0,)):
        argv = list(map(str, argv))
        row = self.add(section, label, command=argv)
        left = self.deadline - time.monotonic()
        if left <= 0:
            row.update(status="budget-exhausted")
            return row
        if not shutil.which(argv[0]):
            row.update(status="missing-tool", detail=f"{argv[0]} is not installed or not in PATH")
            return row
        started = time.monotonic()
        env = {**os.environ, "LC_ALL": "C", "LANG": "C", "TERM": "dumb", "NO_COLOR": "1",
               "SYSTEMD_COLORS": "0", "SYSTEMD_PAGER": "cat", "GIT_OPTIONAL_LOCKS": "0",
               "GIT_TERMINAL_PROMPT": "0"}
        try:
            proc = subprocess.Popen(argv, cwd=cwd, env=env, stdin=subprocess.DEVNULL,
                                    stdout=subprocess.PIPE, stderr=subprocess.PIPE, start_new_session=True)
        except OSError as exc:
            row.update(status="unavailable", detail=str(exc))
            return row
        chunks = {"output": bytearray(), "stderr": bytearray()}
        limit = self.args.max_bytes
        end = started + min(self.args.timeout, left)
        try:
            with selectors.DefaultSelector() as selector:
                for stream, name in ((proc.stdout, "output"), (proc.stderr, "stderr")):
                    os.set_blocking(stream.fileno(), False)
                    selector.register(stream, selectors.EVENT_READ, name)
                while selector.get_map():
                    remaining = end - time.monotonic()
                    if remaining <= 0:
                        row["status"] = "timeout"
                        break
                    for key, _ in selector.select(min(remaining, .1)):
                        data = os.read(key.fileobj.fileno(), 16384)
                        if not data:
                            selector.unregister(key.fileobj)
                            continue
                        name = key.data
                        room = limit - len(chunks[name])
                        chunks[name].extend(data[:room])
                        if len(data) > room:
                            row["status"] = "truncated"
                            break
                    if row["status"] == "truncated":
                        break
                if row["status"] == "ok":
                    try:
                        proc.wait(timeout=max(.001, end - time.monotonic()))
                    except subprocess.TimeoutExpired:
                        row["status"] = "timeout"
        finally:
            # Descendants can retain pipe FDs or outlive a timed-out parent.
            if row["status"] in ("timeout", "truncated") or proc.poll() is None:
                try:
                    os.killpg(proc.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
            proc.wait()
            proc.stdout.close()
            proc.stderr.close()
        row.update(returncode=proc.returncode, duration_seconds=round(time.monotonic() - started, 3))
        for name, data in chunks.items():
            row[name] = data.decode("utf-8", "replace")
        if row["status"] == "ok" and proc.returncode not in ok_codes:
            row["status"] = "error"
        if argv[0] == "systemctl" and "not running in this container" in row.get("output", "").lower():
            row["status"] = "unavailable"
        if transform and row["status"] == "ok":
            try:
                row["data"] = transform(row.pop("output"))
            except (ValueError, TypeError, KeyError) as exc:
                row.pop("output", None)
                row.update(status="invalid-output", detail=str(exc))
        elif transform:
            # Never expose partial unfiltered Nix configuration or derivation env.
            row.pop("output", None)
        return row

    def journal(self, section, label, unit=None, user=False, priority=None):
        argv = ["journalctl", "--no-pager", "--quiet", "--output=short-iso", "--boot", str(self.args.boot),
                "--lines", str(self.args.lines)]
        if user:
            argv.append("--user")
        if unit:
            argv += ["--unit", unit]
        if priority:
            argv += ["--priority", priority]
        row = self.run(section, label, argv)
        if "permission" in row.get("stderr", "").lower() or "not seeing messages" in row.get("stderr", "").lower():
            row["status"] = "restricted"
        return row

    def get_settings(self):
        if self.settings is None:
            def filtered(output):
                # Nix's JSON includes the full manual descriptions and can exceed
                # the output cap. Plain config show has the same effective values
                # without that documentation; filter before recording any output.
                data = {}
                list_keys = {"substituters", "extra-substituters", "trusted-substituters", "trusted-public-keys",
                             "experimental-features", "extra-experimental-features", "allowed-users", "trusted-users"}
                for line in output.splitlines():
                    if "=" not in line:
                        continue
                    key, value = (part.strip() for part in line.split("=", 1))
                    if key not in SETTING_KEYS:
                        continue
                    if key == "builders":
                        data[key] = bool(value)
                    elif key in list_keys:
                        data[key] = shlex.split(value)
                    elif value in ("true", "false"):
                        data[key] = value == "true"
                    elif re.fullmatch(r"[0-9]+", value):
                        data[key] = int(value)
                    else:
                        data[key] = value
                if not data:
                    raise ValueError("No recognized Nix settings in command output")
                return data
            row = self.run("nix", "effective client settings (allowlist, no access tokens)",
                           ["nix", "--extra-experimental-features", "nix-command", "config", "show"], filtered)
            self.settings = row.get("data", {})
        return self.settings

    def config(self):
        if self.repo is not None:
            return
        conf = Path(os.environ.get("NX_CONF", "/etc/nixctl.conf"))
        values = {}
        try:
            with conf.open() as stream:
                for line in stream.read(MAX_FILE).splitlines():
                    if "=" in line and not line.lstrip().startswith("#"):
                        key, value = line.split("=", 1)
                        if key.strip() in ("REPO", "HOST"):
                            parts = shlex.split(value)
                            values[key.strip()] = parts[0] if parts else ""
        except (OSError, ValueError) as exc:
            self.add("repo", "nx configuration", "unavailable", path=str(conf), detail=str(exc))
        self.repo = Path(self.args.repo or values.get("REPO") or os.getcwd()).expanduser().resolve()
        self.host = self.args.host or values.get("HOST")
        self.add("repo", "diagnostic target", data={"config": str(conf), "repo": str(self.repo), "host": self.host,
                                                    "repo_override": bool(self.args.repo)})

    def system(self):
        self.file("system", "/etc/os-release")
        self.run("system", "kernel", ["uname", "-srm"])
        for path in ("/proc/uptime", "/proc/meminfo", "/proc/loadavg", "/proc/pressure/cpu", "/proc/pressure/memory", "/proc/pressure/io"):
            self.file("system", path)
        for path in ("/", "/nix", "/boot", str(Path.home())):
            try:
                usage = shutil.disk_usage(path)
                fs = os.statvfs(path)
                data = {"path": path, "total_bytes": usage.total, "free_bytes": usage.free,
                        "used_percent": round(usage.used * 100 / usage.total, 1), "free_inodes": fs.f_favail}
                self.add("system", "disk space", data=data)
                if data["used_percent"] >= 95 or (fs.f_files > 0 and fs.f_favail / fs.f_files < .02):
                    self.finding("warning", "system", f"Disk space or inodes are low on {path}.", "nx clean --dry-run")
            except OSError as exc:
                self.add("system", f"disk space {path}", "unavailable", detail=str(exc))

    def nix(self):
        self.run("nix", "Nix version", ["nix", "--version"])
        self.get_settings()
        self.run("nix", "daemon/socket", ["systemctl", "show", "nix-daemon.service", "nix-daemon.socket",
                 "--property=Id,LoadState,ActiveState,SubState,Result,ExecMainStatus", "--no-pager"])
        self.add("nix", "environment switches (allowlist)", data={key: os.environ[key] for key in
                 ("NIX_REMOTE", "NIX_PATH", "NIX_PROFILES", "NIX_SSL_CERT_FILE", "NIX_USER_CONF_FILES") if key in os.environ})
        self.add("nix", "NIX_CONFIG", data={"set": "NIX_CONFIG" in os.environ,
                 "note": "Raw NIX_CONFIG is omitted. Client settings can differ from daemon settings and per-command options."})
        path = Path("/etc/nix/nix.conf")
        try:
            settings = {}
            with path.open() as stream:
                text = stream.read(MAX_FILE)
            for line in text.splitlines():
                if "=" in line and not line.lstrip().startswith("#"):
                    key, value = line.split("=", 1)
                    if key.strip() in SETTING_KEYS:
                        settings[key.strip()] = bool(value.strip()) if key.strip() == "builders" else value.strip()
            self.add("nix", "system nix.conf allowlist (includes not expanded)", data=settings)
        except OSError as exc:
            self.add("nix", "system nix.conf", "unavailable", detail=str(exc))

    def cache(self):
        settings = self.get_settings()
        keys = ("substitute", "substituters", "extra-substituters", "trusted-substituters", "trusted-public-keys", "require-sigs", "fallback", "narinfo-cache-negative-ttl")
        self.add("cache", "effective client cache policy", "ok" if settings else "unavailable",
                 data={key: settings.get(key, "unknown") for key in keys})
        self.add("cache", "interpretation", output=(
            "A configured cache does not guarantee every output is cached. A missing substitute can cause a local build. "
            "fallback=true permits a source build after a substitute download fails; fallback=false still permits builds "
            "for outputs absent from caches. Package checks run during a local build because the derivation enables them. "
            "This report does not disable tests, change cache policy or retry a build. A negative cache entry can temporarily hide a newly published substitute."))
        if settings.get("substitute") is False:
            self.finding("warning", "cache", "Substitution is disabled in the effective client settings.", "Inspect nix config show and NIX_CONFIG/per-command options.")
        if settings.get("fallback") is True:
            self.finding("warning", "cache", "fallback=true is active in the client settings.", "Inspect the configuration source; standard fallback is false.")
        if settings.get("require-sigs") is False:
            self.finding("warning", "cache", "Signature checking is disabled in the effective client settings.")
        if self.args.probe_cache:
            urls = settings.get("substituters", [])
            if isinstance(urls, str):
                urls = urls.split()
            for url in list(dict.fromkeys(urls))[:8]:
                parsed = urllib.parse.urlsplit(url)
                def cache_url(name):
                    # Nix store parameters are not part of the HTTP endpoint.
                    query = urllib.parse.urlencode([(k, v) for k, v in urllib.parse.parse_qsl(parsed.query)
                                                     if k not in ("priority", "trusted", "want-mass-query")])
                    return urllib.parse.urlunsplit((parsed.scheme, parsed.netloc, parsed.path.rstrip("/") + "/" + name, query, ""))
                self.http_probe(cache_url("nix-cache-info"))
                if self.args.store_path and not self.args.store_path.endswith(".drv"):
                    self.http_probe(cache_url(Path(self.args.store_path).name[:32] + ".narinfo"))

    def http_probe(self, url):
        parsed = urllib.parse.urlsplit(url)
        if (parsed.scheme not in ("http", "https") or parsed.username or parsed.password
                or any(re.search(r"(?i)token|password|secret|auth|(?:^|_)key$|signature", key)
                       for key, _ in urllib.parse.parse_qsl(parsed.query))):
            self.add("cache", "explicit cache HEAD probe", "skipped", url=url,
                     detail="Only HTTP(S) caches without embedded credentials or credential query parameters are probed")
            return
        # Isolate even DNS resolution behind the same process timeout/budget.
        # No redirects, response bodies or authentication are requested.
        script = """import json, sys, urllib.request, urllib.error
class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None
try:
    with urllib.request.build_opener(NoRedirect).open(
        urllib.request.Request(sys.argv[1], method='HEAD'), timeout=float(sys.argv[2])) as r:
        print(json.dumps({'http_status': r.status}))
except urllib.error.HTTPError as e:
    print(json.dumps({'http_status': e.code}))
except (OSError, ValueError) as e:
    print(str(e), file=sys.stderr)
    sys.exit(1)
"""
        row = self.run("cache", "explicit cache HEAD probe", [sys.executable, "-I", "-c", script, url, str(self.args.timeout)], json.loads)
        row["command"] = ["HTTP HEAD", url]
        code = row.get("data", {}).get("http_status")
        if code == 404:
            row.update(status="absent", detail="HTTP 404: no entry at this URL")
        elif code and not 200 <= code < 300:
            row.update(status="error", detail="HEAD failed; redirects and unsupported HEAD do not establish cache availability")

    def repository(self):
        self.config()
        for label, argv in (
            ("branch/dirty state", ["status", "--short", "--branch", "--untracked-files=no"]),
            ("commit", ["log", "-1", "--format=%H %cI"]),
            ("remote URLs", ["remote", "-v"]),
            ("unresolved conflicts", ["diff", "--name-only", "--diff-filter=U"]),
            ("lock modification", ["diff", "--stat", "HEAD", "--", "flake.lock"]),
        ):
            row = self.run("repo", label, ["git", "--no-optional-locks", "-C", self.repo, *argv])
            if label == "unresolved conflicts" and row.get("output", "").strip():
                self.finding("error", "repo", "The repository has unresolved merge conflicts.", "Resolve conflicts before nx update or nx switch.")
        row = self.file("repo", self.repo / "flake.lock", "lock inputs (metadata only)")
        if row["status"] == "ok":
            try:
                lock = json.loads(row.pop("output"))
                nodes = lock["nodes"]
                row["data"] = {"root": lock["root"], "root_inputs": nodes[lock["root"]].get("inputs", {}),
                    "nodes": {name: {"locked": {k: v for k, v in node.get("locked", {}).items() if k in
                        ("type", "owner", "repo", "rev", "lastModified", "narHash")}, "inputs": node.get("inputs", {})}
                        for name, node in nodes.items()}}
            except (ValueError, KeyError, TypeError) as exc:
                row.pop("output", None)
                row.update(status="invalid-output", detail=str(exc))
                self.finding("error", "repo", "flake.lock is invalid or has an unsupported structure.")
        else:
            row.pop("output", None)
        if self.host and re.fullmatch(r"[A-Za-z0-9_-]+", self.host):
            row = self.file("repo", self.repo / "hosts" / self.host / "features.nix", "host feature switches")
            if "output" in row:
                row["data"] = re.findall(r"(?m)^\s*(my\.[\w.]+)\s*=\s*([^;\n]+);", row.pop("output"))

    def profiles(self):
        argv = ["nix", "--extra-experimental-features", "nix-command", "profile"]
        profile = ["--profile", str(Path(self.args.profile).expanduser())] if self.args.profile else []
        self.run("profiles", "user profile packages", [*argv, "list", *profile, "--json"], json.loads)
        self.run("profiles", "user profile history", [*argv, "history", *profile])
        self.run("profiles", "system generations", ["nix-env", "--profile", "/nix/var/nix/profiles/system", "--list-generations"])

    def boot(self):
        paths = {"running": "/run/current-system", "booted": "/run/booted-system", "selected": "/nix/var/nix/profiles/system"}
        targets = {}
        for label, path in paths.items():
            try:
                target = str(Path(path).resolve(strict=True))
                targets[label] = target
                self.add("boot", label, data={"path": path, "target": target})
                self.file("boot", Path(target) / "nixos-version", f"{label} NixOS version")
                kernel = Path(target) / "kernel"
                self.add("boot", f"{label} kernel", "ok" if kernel.exists() else "unavailable", target=str(kernel.resolve()))
            except OSError as exc:
                self.add("boot", label, "unavailable", detail=str(exc))
        if "running" in targets and "selected" in targets and targets["running"] != targets["selected"]:
            self.finding("warning", "boot", "Selected and running system differ; a boot-only activation or rollback may be pending.", "nx gen list")
        running = Path("/run/current-system/kernel").resolve()
        booted = Path("/run/booted-system/kernel").resolve()
        if running.exists() and booted.exists() and running != booted:
            self.finding("warning", "boot", "The running configuration selects a different kernel from the booted configuration.", "Reboot when convenient to load the selected kernel.")
        self.run("boot", "boot partition usage", ["df", "-h", "/boot"])
        self.run("boot", "available journal boots", ["journalctl", "--list-boots", "--no-pager", "--quiet"])
        if self.args.full:
            self.run("boot", "boot loader", ["bootctl", "status", "--no-pager"])

    def services(self):
        for user in (False, True):
            scope = ["--user"] if user else []
            row = self.run("services", f"failed {'user' if user else 'system'} units", ["systemctl", *scope, "--failed", "--no-legend", "--plain", "--no-pager"])
            if row["status"] == "ok" and row.get("output", "").strip():
                units = [line.split()[0] for line in row["output"].splitlines()
                         if len(line.split()) >= 4 and "failed" in line.split()[2:4]]
                if units:
                    row["data"] = {"failed_units": units}
                    self.finding("error", "services", f"Failed {'user' if user else 'system'} units were found.", "nx debug services --user-unit UNIT" if user else "nx debug services --unit UNIT")
                else:
                    row.update(status="invalid-output", detail="systemctl returned nonempty output without failed unit rows")
        units = [(False, u) for u in self.args.unit] + [(True, u) for u in self.args.user_unit]
        if self.args.full:
            units += [(False, "nix-daemon.service"), (False, "greetd.service"), (True, "xdg-desktop-portal.service")]
        for user, unit in dict.fromkeys(units):
            self.run("services", f"{'user' if user else 'system'} {unit}", ["systemctl", *(["--user"] if user else []), "show", unit,
                     "--property=Id,LoadState,ActiveState,SubState,Result,ExecMainStatus,NRestarts,ActiveEnterTimestamp", "--no-pager"])
            self.journal("services", f"{unit} journal", unit, user)

    def hardware(self):
        commands = [("CPU", ["lscpu"]), ("PCI devices and drivers", ["lspci", "-nnk"]),
                    ("block devices", ["lsblk", "--json", "--output=NAME,TYPE,SIZE,FSTYPE,MOUNTPOINTS,ROTA"]),
                    ("audio services", ["wpctl", "status", "--name"])]
        if self.args.full:
            commands += [("USB device classes", ["lsusb", "-t"]), ("loaded drivers", ["lsmod"]),
                         ("NVIDIA", ["nvidia-smi", "--query-gpu=name,driver_version,memory.total,memory.used,temperature.gpu", "--format=csv"])]
        for label, argv in commands:
            self.run("hardware", label, argv)
        for device in sorted(Path("/sys/class/drm").glob("card[0-9]*"))[:16]:
            if "-" not in device.name:
                for attr in ("device/vendor", "device/device", "device/uevent"):
                    self.file("hardware", device / attr)

    def network(self):
        for label, argv in (
            ("link state (no addresses)", ["ip", "-brief", "link"]),
            ("NetworkManager state", ["nmcli", "--terse", "--fields", "DEVICE,TYPE,STATE", "device", "status"]),
            ("resolver state", ["resolvectl", "status", "--no-pager"]),
        ):
            self.run("network", label, argv)
        self.add("network", "connectivity", "not-tested", detail="No ping, DNS lookup or external connection unless --probe-cache was requested.")

    def desktop(self):
        keys = ("XDG_SESSION_TYPE", "XDG_CURRENT_DESKTOP", "XDG_SESSION_DESKTOP", "WAYLAND_DISPLAY", "DISPLAY", "XDG_RUNTIME_DIR", "QT_QPA_PLATFORM", "GDK_BACKEND")
        self.add("desktop", "session environment (allowlist)", data={key: os.environ[key] for key in keys if key in os.environ})
        # Comm names only: process arguments can contain passwords, URLs or document names.
        def desktop_processes(output):
            names = ("mango", "Hyprland", "niri", "sway", "kwin_wayland", "noctalia", "qs", "quickshell", "caelestia", "Xwayland", "pipewire", "wireplumber", "xdg-desktop")
            return [line for line in output.splitlines() if any(name.lower() in line.lower() for name in names)]
        self.run("desktop", "desktop processes (no arguments)", ["ps", "-eo", "pid=,comm="], desktop_processes)
        self.run("desktop", "portals and audio", ["systemctl", "--user", "show", "xdg-desktop-portal.service", "pipewire.service", "wireplumber.service",
                 "--property=Id,LoadState,ActiveState,SubState,Result", "--no-pager"])
        if self.args.full:
            self.run("desktop", "display outputs", ["wlr-randr"])

    def logs(self):
        self.journal("logs", "system warnings", priority="warning")
        self.journal("logs", "user warnings", user=True, priority="warning")
        self.journal("logs", "Nix daemon", unit="nix-daemon.service")

    def build(self):
        path = self.args.store_path
        if not path:
            self.add("build", "build target", "not-tested", detail="Pass --store-path /nix/store/HASH-name[.drv]")
            return
        self.add("build", "requested store path", data={"path": path, "exists_locally": Path(path).exists()})
        common = ["nix", "--extra-experimental-features", "nix-command", "--offline",
                  "--option", "substituters", "", "--option", "extra-substituters", ""]
        def derivation_summary(output):
            data = json.loads(output)
            if "derivations" in data:
                data = data["derivations"]
            return {key: {field: value[field] for field in ("name", "system", "builder", "inputDrvs", "inputSrcs", "outputs") if field in value}
                    for key, value in data.items() if isinstance(value, dict)}
        if path.endswith(".drv"):
            self.run("build", "derivation dependencies and outputs (env/args omitted)", [*common, "derivation", "show", path], derivation_summary)
        else:
            self.run("build", "local output metadata", [*common, "path-info", "--json", path], json.loads)
            self.run("build", "local deriver", ["nix-store", "--query", "--deriver", path])
        self.run("build", "saved local build log", [*common, "log", path])
        self.add("build", "build diagnosis", output="No build was started. A missing log means it is unavailable locally, not that the build succeeded. Pass a failing dependency's .drv path to inspect that dependency directly. --probe-cache with an output path checks that exact output's narinfo, not all dependencies.")


def render_text(report):
    lines = [f"nx debug | {report['created_at']} | schema {report['schema_version']}",
             f"Collection: {report['summary']['checks']} checks; {report['summary']['incomplete']} incomplete; {len(report['findings'])} findings",
             "Read-only collection. Redacted report; review it before sharing.", ""]
    for finding in report["findings"]:
        lines.append(f"{finding['severity'].upper()} [{finding['section']}] {finding['message']}")
        if finding.get("next_step"):
            lines.append("  Next: " + finding["next_step"])
    for name, rows in report["sections"].items():
        lines += ["", f"=== {name}: {SECTIONS[name]} ==="]
        for row in rows:
            lines.append(f"[{row['status']}] {row['label']}")
            if row.get("command"):
                lines.append("  $ " + shlex.join(row["command"]))
            for key in ("data", "output", "stderr", "detail", "path", "target", "url", "http_status"):
                if key in row and row[key] not in ("", None):
                    value = json.dumps(row[key], ensure_ascii=False, indent=2) if isinstance(row[key], (dict, list)) else str(row[key])
                    lines.extend("  " + line for line in (f"{key}: " + value).splitlines())
    return "\n".join(lines) + "\n"


def command(args):
    sections = list(dict.fromkeys(args.sections or DEFAULT_SECTIONS))
    unknown = [s for s in sections if s not in SECTIONS]
    if unknown:
        raise SystemExit("nx debug: unknown section(s): " + ", ".join(unknown) + "; see nx debug --list")
    if args.list:
        print(json.dumps(SECTIONS, indent=2) if args.json else "\n".join(f"{name:10} {text}" for name, text in SECTIONS.items()))
        return 0
    if not .1 <= args.timeout <= 60 or not 1 <= args.budget <= 600 or not 1024 <= args.max_bytes <= 1048576:
        raise SystemExit("nx debug: timeout must be 0.1..60, budget 1..600, max-bytes 1024..1048576")
    if args.lines is None:
        args.lines = 400 if args.full else 80
    if not 1 <= args.lines <= 2000 or args.boot > 0:
        raise SystemExit("nx debug: lines must be 1..2000; boot must be 0 or negative")
    if len(args.unit) + len(args.user_unit) > 20 or any(not re.fullmatch(r"[A-Za-z0-9_.:@\\-]+", u) or u.startswith("-") for u in [*args.unit, *args.user_unit]):
        raise SystemExit("nx debug: provide at most 20 literal systemd unit names, without options or patterns")
    if args.store_path and not STORE_PATH.fullmatch(args.store_path):
        raise SystemExit("nx debug: --store-path must be a single absolute /nix/store/HASH-name path")
    for enabled, section in ((args.store_path, "build"), (args.unit or args.user_unit, "services"), (args.probe_cache, "cache")):
        if enabled and section not in sections:
            sections.append(section)
    collector = Collector(args)
    started = time.monotonic()
    for section in sections:
        if not args.json and sys.stderr.isatty():
            print(f"nx debug: collecting {section}...", file=sys.stderr)
        try:
            getattr(collector, "repository" if section == "repo" else section)()
        except (OSError, ValueError, KeyError, TypeError, RuntimeError) as exc:
            collector.add(section, "section collection", "error", detail=str(exc))
    incomplete = sum(row["status"] not in ("ok", "not-tested") for rows in collector.sections.values() for row in rows)
    report = {"schema_version": 1, "created_at": datetime.now(timezone.utc).isoformat(),
              "duration_seconds": round(time.monotonic() - started, 3), "requested_sections": sections,
              "options": {key: getattr(args, key) for key in ("full", "probe_cache", "boot", "lines", "timeout", "budget", "max_bytes")},
              "privacy": {"redacted": True, "review_before_sharing": True,
                          "note": "Common credentials, home/user identifiers, email and IP/MAC addresses are masked best-effort. Logs, paths, domain names and device descriptions can still identify a system. No upload is performed."},
              "summary": {"checks": sum(map(len, collector.sections.values())), "incomplete": incomplete},
              "findings": collector.findings, "sections": collector.sections}
    report = Redactor().data(report)
    output = json.dumps(report, ensure_ascii=False, indent=2) + "\n" if args.json else render_text(report)
    if args.output:
        try:
            # O_EXCL also rejects existing symlinks; never follow or overwrite a report.
            fd = os.open(Path(args.output).expanduser(), os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            with os.fdopen(fd, "w", encoding="utf-8") as stream:
                stream.write(output)
        except OSError as exc:
            print("nx debug: cannot save report: " + str(exc), file=sys.stderr)
            return 2
    print(output, end="")
    return 1 if args.strict and (incomplete or collector.findings) else 0
