"""Read-only diagnostics, bounded subprocesses, privacy and report contracts."""
import contextlib
import http.server
import importlib.util
import io
import json
import os
import socket
import stat
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("nx", ROOT / "pkgs/nx/nx.py")
nx = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(nx)
debug = nx.debug_module()
STORE = "/nix/store/" + "a" * 32 + "-fixture"


def arguments(*argv):
    return nx.build_parser().parse_args(["debug", *argv])


class ProcessTests(unittest.TestCase):
    def collector(self, *argv):
        return debug.Collector(arguments(*argv))

    def test_success_stdin_closed_and_nonzero(self):
        c = self.collector()
        row = c.run("system", "stdin", [sys.executable, "-c", "import sys; print(repr(sys.stdin.read()))"])
        self.assertEqual(row["status"], "ok")
        self.assertEqual(row["output"].strip(), "''")
        row = c.run("system", "error", [sys.executable, "-c", "import sys; print('failed', file=sys.stderr); sys.exit(3)"])
        self.assertEqual((row["status"], row["returncode"]), ("error", 3))
        self.assertIn("failed", row["stderr"])

    def test_missing_and_budget(self):
        c = self.collector()
        self.assertEqual(c.run("nix", "missing", ["nx-nonexistent-test-tool"])["status"], "missing-tool")
        c.deadline = time.monotonic() - 1
        with mock.patch.object(debug.subprocess, "Popen", side_effect=AssertionError("process launched")):
            self.assertEqual(c.run("nix", "budget", [sys.executable])["status"], "budget-exhausted")

    def test_timeout_kills_descendants_holding_pipes(self):
        c = self.collector("--timeout", ".15")
        script = "import subprocess, sys; p=subprocess.Popen([sys.executable,'-c','import time; time.sleep(60)']); print(p.pid,flush=True)"
        started = time.monotonic()
        row = c.run("system", "descendant", [sys.executable, "-c", script])
        self.assertEqual(row["status"], "timeout")
        self.assertLess(time.monotonic() - started, 2)
        child = Path("/proc") / row["output"].strip() / "stat"
        # A killed orphan can briefly remain a zombie until init reaps it.
        if child.exists():
            self.assertIn(child.read_text().split(")", 1)[1].strip().split()[0], ("Z", "X"))

    def test_closed_pipes_do_not_bypass_timeout(self):
        c = self.collector("--timeout", ".1")
        row = c.run("system", "closed", [sys.executable, "-c", "import os,time; os.close(1); os.close(2); time.sleep(60)"])
        self.assertEqual(row["status"], "timeout")

    def test_output_is_capped_and_process_stopped(self):
        c = self.collector("--max-bytes", "1024")
        row = c.run("logs", "flood", [sys.executable, "-c", "import os;\nwhile True: os.write(1,b'x'*4096)"])
        self.assertEqual(row["status"], "truncated")
        self.assertEqual(len(row["output"]), 1024)

    def test_parse_failure_does_not_leak_unfiltered_output(self):
        c = self.collector()
        row = c.run("nix", "settings", [sys.executable, "-c", "print('secret arbitrary content')"], json.loads)
        self.assertEqual(row["status"], "invalid-output")
        self.assertNotIn("output", row)
        row = c.run("nix", "settings", [sys.executable, "-c", "print('secret'); raise SystemExit(1)"], json.loads)
        self.assertNotIn("output", row)


class DiagnosticTests(unittest.TestCase):
    def test_config_filters_tokens_and_remote_builders(self):
        raw = {"substituters": {"value": ["https://cache.nixos.org/"]}, "fallback": {"value": False},
               "access-tokens": {"value": "NEVER_SHOW"}, "builders": {"value": "ssh://secret:pass@builder"}}
        c = debug.Collector(arguments())
        # Keep the real filtering callback while replacing only the process.
        original = c.run
        def routed(section, label, argv, transform=None, **kwargs):
            row = original(section, label, [sys.executable, "-c", "print(" + repr(json.dumps(raw)) + ")"], transform)
            row["command"] = argv
            return row
        with mock.patch.object(c, "run", side_effect=routed):
            settings = c.get_settings()
        self.assertEqual(settings["builders"], True)
        self.assertEqual(settings["fallback"], False)
        self.assertNotIn("access-tokens", settings)
        self.assertNotIn("NEVER_SHOW", json.dumps(c.sections))
        self.assertNotIn("secret:pass", json.dumps(c.sections))

    def test_default_cache_does_not_contact_network(self):
        c = debug.Collector(arguments("cache"))
        c.settings = {"substitute": False, "fallback": True, "require-sigs": False}
        with mock.patch.object(c, "http_probe", side_effect=AssertionError("network used")):
            c.cache()
        self.assertEqual(len(c.findings), 3)
        self.assertIn("absent from caches", c.sections["cache"][1]["output"])

    def test_explicit_head_404_and_no_redirect(self):
        requests = []
        class Handler(http.server.BaseHTTPRequestHandler):
            def do_HEAD(self):
                requests.append(self.path)
                self.send_response(302 if self.path == "/redirect" else 404)
                if self.path == "/redirect":
                    self.send_header("Location", "/should-not-follow")
                self.end_headers()
            def log_message(self, *args):
                pass
        with http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler) as server:
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            try:
                c = debug.Collector(arguments("--probe-cache"))
                base = f"http://127.0.0.1:{server.server_port}"
                c.http_probe(base + "/missing")
                c.http_probe(base + "/redirect")
                c.http_probe("https://user:pass@example.com/nix-cache-info")
                c.http_probe("file:///nix/store")
            finally:
                server.shutdown()
                thread.join()
        self.assertEqual([r["status"] for r in c.sections["cache"]], ["absent", "error", "skipped", "skipped"])
        self.assertEqual(requests, ["/missing", "/redirect"])

    def test_unit_commands_are_literal_and_journals_bounded(self):
        args = arguments("services", "--unit", "greetd.service", "--user-unit", "pipewire.service", "--boot", "-1", "--lines", "23")
        c = debug.Collector(args)
        commands = []
        def fake(section, label, argv, **kwargs):
            commands.append(argv)
            return c.add(section, label, output="")
        with mock.patch.object(c, "run", side_effect=fake):
            c.services()
        journals = [a for a in commands if a[0] == "journalctl"]
        self.assertEqual(len(journals), 2)
        for argv in journals:
            self.assertIn("23", argv)
            self.assertIn("-1", argv)
        self.assertIn("--user", journals[1])
        self.assertTrue(all("sudo" not in a for a in commands))

    def test_failed_unit_is_a_finding(self):
        c = debug.Collector(arguments("services"))
        with mock.patch.object(c, "run", side_effect=lambda section, label, argv: c.add(section, label, output="broken.service failed")):
            c.services()
        self.assertEqual(len(c.findings), 2)

    def test_missing_config_does_not_abort_repository_diagnosis(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "flake.lock").write_text("{ invalid")
            c = debug.Collector(arguments("repo", "--repo", tmp))
            with mock.patch.dict(os.environ, NX_CONF=str(root / "missing")), mock.patch.object(c, "run", side_effect=lambda s, l, a: c.add(s, l, "error")):
                c.repository()
            self.assertEqual(c.repo, root)
            self.assertTrue(any("invalid" in f["message"] for f in c.findings))
            self.assertNotIn("{ invalid", json.dumps(c.sections))

    def test_build_has_no_env_args_and_no_fetchers(self):
        c = debug.Collector(arguments("build", "--store-path", STORE + ".drv"))
        raw = {STORE + ".drv": {"builder": "/bin/sh", "inputDrvs": {STORE + "-dep.drv": ["out"]},
                               "outputs": {"out": {"path": STORE}}, "env": {"password": "SECRET"}, "args": ["SECRET"]}}
        original = c.run
        calls = []
        def fake(section, label, argv, transform=None, **kwargs):
            calls.append(argv)
            if transform:
                row = original(section, label, [sys.executable, "-c", "print(" + repr(json.dumps(raw)) + ")"], transform)
                row["command"] = argv
                return row
            return c.add(section, label, output="saved log")
        with mock.patch.object(c, "run", side_effect=fake):
            c.build()
        self.assertNotIn("SECRET", json.dumps(c.sections))
        for argv in calls:
            self.assertIn("--offline", argv)
            self.assertIn("substituters", argv)
            self.assertNotIn("build", argv)

    def test_restricted_journal_is_not_success(self):
        c = debug.Collector(arguments())
        with mock.patch.object(c, "run", return_value={"status": "ok", "stderr": "Permission denied"}):
            self.assertEqual(c.journal("logs", "journal")["status"], "restricted")


class ReportTests(unittest.TestCase):
    def invoke(self, *argv):
        stdout, stderr = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
            code = debug.command(arguments(*argv))
        return code, stdout.getvalue(), stderr.getvalue()

    def test_redaction_including_nested_fields_and_controls(self):
        with mock.patch.dict(os.environ, USER="alice", LOGNAME="alice", HOSTNAME="private-host"), mock.patch.object(debug.Path, "home", return_value=Path("/home/alice")), mock.patch.object(debug.socket, "gethostname", return_value="private-host"):
            value = debug.Redactor().data({"output": ["/home/alice/file alice private-host me@example.org 192.168.1.5 2001:db8::1 aa:bb:cc:dd:ee:ff",
                "https://name:password@cache.example/a?token=abc", "access-tokens = github.com=secret", "ghp_abcdefgh", "\x1b[31mred\x1b[0m\x00"]})
        text = json.dumps(value)
        for secret in ("alice", "private-host", "me@example.org", "192.168.1.5", "2001:db8::1", "aa:bb:cc:dd:ee:ff", "password@", "token=abc", "github.com=secret", "ghp_abcdefgh", "\\u001b", "\\u0000"):
            self.assertNotIn(secret, text)

    def test_json_export_permissions_and_no_overwrite_or_symlink(self):
        with tempfile.TemporaryDirectory() as tmp, mock.patch.object(debug.Collector, "system", lambda c: c.add("system", "test", output="password=SECRET")):
            path = Path(tmp) / "report.json"
            code, output, _ = self.invoke("system", "--json", "--output", str(path))
            self.assertEqual(code, 0)
            self.assertEqual(path.read_text(), output)
            self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o600)
            self.assertEqual(json.loads(output)["schema_version"], 1)
            self.assertNotIn("SECRET", output)
            self.assertEqual(self.invoke("system", "--output", str(path))[0], 2)
            link = Path(tmp) / "link"
            link.symlink_to(path)
            self.assertEqual(self.invoke("system", "--output", str(link))[0], 2)
            self.assertEqual(path.read_text(), output)

    def test_incomplete_report_and_strict_exit(self):
        with mock.patch.object(debug.Collector, "nix", lambda c: c.add("nix", "test", "missing-tool")):
            self.assertEqual(self.invoke("nix")[0], 0)
            code, output, _ = self.invoke("nix", "--json", "--strict")
            self.assertEqual(code, 1)
            self.assertEqual(json.loads(output)["summary"]["incomplete"], 1)

    def test_validation_before_any_diagnostics(self):
        invalid = [("wrong-section",), ("--timeout", "nan"), ("--budget", "0"), ("--lines", "2001"),
                   ("--boot", "1"), ("--max-bytes", "1"), ("--unit=--all",), ("--unit", "*.service"),
                   ("--store-path", "github:NixOS/nixpkgs#hello"), ("--store-path", STORE + "/etc")]
        with mock.patch.object(debug.Collector, "__init__", side_effect=AssertionError("collection started")):
            for argv in invalid:
                with self.subTest(argv=argv), self.assertRaises(SystemExit):
                    self.invoke(*argv)

    def test_requested_target_sections_are_included(self):
        with mock.patch.object(debug.Collector, "system", lambda c: c.add("system", "test")), mock.patch.object(debug.Collector, "build", lambda c: c.add("build", "test")), mock.patch.object(debug.Collector, "services", lambda c: c.add("services", "test")):
            _, output, _ = self.invoke("system", "--json", "--store-path", STORE, "--unit", "greetd.service")
        self.assertEqual(json.loads(output)["requested_sections"], ["system", "build", "services"])

    def test_isolated_entry_point_and_list_do_not_need_configuration(self):
        env = {**os.environ, "NX_CONF": "/nonexistent/nixctl.conf"}
        result = subprocess.run([sys.executable, "-I", str(ROOT / "pkgs/nx/nx.py"), "debug", "--list", "--json"],
                                env=env, cwd="/", capture_output=True, text=True, timeout=5)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(set(json.loads(result.stdout)), set(debug.SECTIONS))


if __name__ == "__main__":
    unittest.main()
