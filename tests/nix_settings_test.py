"""Smoke-test the actual Rust frontend, including startup in a controlling PTY."""
import fcntl
import json
import os
import pty
import select
import shlex
import signal
import struct
import subprocess
import tempfile
import termios
import time
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BINARY = os.environ.get("NIX_SETTINGS_BINARY", str(ROOT / "nix-settings/target/debug/nix-settings"))


class FrontendTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.home = Path(self.temp.name)
        self.repo = self.home / "checkout ' with spaces"
        self.repo.mkdir()
        (self.repo / "flake.nix").write_text("{}")
        host = self.repo / "hosts/nyx"
        host.mkdir(parents=True)
        (host / "features.nix").write_text("{ my.features.gaming.enable = true; }\n")
        subprocess.run(["git", "init", "-q", "-b", "main", str(self.repo)], check=True)
        subprocess.run(["git", "-C", str(self.repo), "add", "flake.nix", "hosts"], check=True)
        subprocess.run(["git", "-C", str(self.repo), "-c", "user.name=Test", "-c", "user.email=test@example.invalid", "commit", "-qm", "fixture"], check=True)
        conf = self.home / "nixctl.conf"
        conf.write_text(f"REPO={shlex.quote(str(self.repo))}\nHOST=nyx\n")
        bindir = self.home / "bin"
        bindir.mkdir()
        nx = bindir / "nx"
        nx.write_text("#!/bin/sh\nexec python3 " + shlex.quote(str(ROOT / "pkgs/nx/nx.py")) + ' "$@"\n')
        nx.chmod(0o755)
        self.env = dict(os.environ, HOME=str(self.home), XDG_CACHE_HOME=str(self.home / "cache"),
                        PATH=str(bindir) + os.pathsep + os.environ["PATH"],
                        NX_CONF=str(conf), NIXCTL_CONF=str(conf), TERM="xterm-256color")

    def test_status_json_reads_configured_host_and_path_without_terminal_or_mutation(self):
        before = (self.repo / "hosts/nyx/features.nix").read_bytes()
        result = subprocess.run([BINARY, "--status-json"], env=self.env, capture_output=True, text=True, timeout=10)
        self.assertEqual(result.returncode, 0, result.stderr)
        value = json.loads(result.stdout)
        self.assertEqual(value["host"], "nyx")
        self.assertEqual(value["repo"], str(self.repo))
        self.assertEqual(value["features"], ["gaming"])
        self.assertEqual((self.repo / "hosts/nyx/features.nix").read_bytes(), before)
        self.assertEqual(subprocess.check_output(["git", "-C", str(self.repo), "status", "--porcelain"]), b"")

    def test_different_backend_configs_fail_before_taking_over_terminal(self):
        env = dict(self.env, NIXCTL_CONF=str(self.home / "other"))
        result = subprocess.run([BINARY, "--status-json"], env=env, capture_output=True, text=True, timeout=10)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("same file", result.stderr)
        self.assertNotIn("\x1b[?1049h", result.stdout)

    def test_first_frame_is_visible_and_quit_restores_a_real_terminal(self):
        child, master = pty.fork()
        if child == 0:
            os.execve(BINARY, [BINARY, "--size-bypass"], self.env)
        fcntl.ioctl(master, termios.TIOCSWINSZ, struct.pack("HHHH", 35, 120, 0, 0))
        output = bytearray()
        deadline = time.monotonic() + 10
        status = None
        answered = 0
        try:
            while b"NIX SETTINGS" not in output and time.monotonic() < deadline:
                if select.select([master], [], [], 0.1)[0]:
                    try: output.extend(os.read(master, 65536))
                    except OSError: break
                    while answered < output.count(b"\x1b[6n"):
                        os.write(master, b"\x1b[1;1R")
                        answered += 1
            self.assertIn(b"NIX SETTINGS", output)
            os.write(master, b"q")
            while time.monotonic() < deadline:
                pid, value = os.waitpid(child, os.WNOHANG)
                if pid:
                    status = value
                    break
                if select.select([master], [], [], 0.1)[0]:
                    try: output.extend(os.read(master, 65536))
                    except OSError: pass
            self.assertIsNotNone(status)
            self.assertEqual(os.waitstatus_to_exitcode(status), 0)
            while select.select([master], [], [], 0.1)[0]:
                try:
                    data = os.read(master, 65536)
                    if not data: break
                    output.extend(data)
                except OSError: break
            self.assertIn(b"\x1b[?1049l", output)
        finally:
            try:
                pid, _ = os.waitpid(child, os.WNOHANG)
                if not pid: os.kill(child, signal.SIGKILL); os.waitpid(child, 0)
            except ChildProcessError: pass
            os.close(master)


if __name__ == "__main__":
    unittest.main()
