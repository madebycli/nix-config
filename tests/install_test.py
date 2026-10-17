"""Exercise the installer's real lock/build/activation transaction with fake tools.

Platform checks and hardware setup are outside this harness. No NixOS, sudo,
network, real hardware files or Git identity is needed.
"""
import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path


SOURCE = (Path(__file__).resolve().parents[1] / "scripts/install.sh").read_text()
PREFIX = SOURCE.split("die()")[0]
HELPERS = "\n".join(line for line in SOURCE.splitlines() if line.startswith(("die()", "info()")))
BODY = SOURCE[SOURCE.index("install_lock_backup=$(mktemp)"):SOURCE.index("\nkeep_updated_lock=1") + len("\nkeep_updated_lock=1")]
STUB = r'''#!/usr/bin/env python3
import json, os, sys
from pathlib import Path
tool = Path(sys.argv[0]).name
args = sys.argv[1:]
with open(os.environ["CALL_LOG"], "a") as f:
    f.write(json.dumps([tool, *args]) + "\n")
cmd = list(args)
while cmd[:1] == ["--option"]:
    cmd = cmd[3:]
stage = ""
if tool == "nix" and cmd[:2] == ["flake", "update"]:
    Path("flake.lock").write_text('{"updated":true}\n')
    stage = "update"
elif tool == "nix" and cmd[:1] == ["eval"]:
    stage = "eval"
elif tool == "nixos-rebuild":
    stage = cmd[0]
if stage and stage == os.environ.get("FAIL_STAGE"):
    sys.exit(23)
'''


class InstallTests(unittest.TestCase):
    def run_install(self, failure="", answer="y"):
        with tempfile.TemporaryDirectory(prefix="nx-install-test-") as d:
            root = Path(d)
            tools = root / "bin"
            tools.mkdir()
            for name in ("nix", "nixos-rebuild"):
                path = tools / name
                path.write_text(STUB)
                path.chmod(0o755)
            sudo = tools / "sudo"
            sudo.write_text('#!/usr/bin/env bash\nexec "$@"\n')
            sudo.chmod(0o755)
            lock = root / "flake.lock"
            original = '{"old":true}\n'
            lock.write_text(original)
            log = root / "calls.jsonl"
            script = PREFIX + HELPERS + '\nHOST=nyx\nASSUME_YES=0\nDIR="$PWD"\n' + BODY
            result = subprocess.run(["bash", "-c", script], cwd=root, text=True,
                                    input=answer + "\n", capture_output=True,
                                    env={**os.environ, "PATH": str(tools) + os.pathsep + os.environ["PATH"],
                                         "CALL_LOG": str(log), "FAIL_STAGE": failure})
            calls = [json.loads(line) for line in log.read_text().splitlines()]
            return result, lock.read_text(), original, calls

    def test_fresh_install_updates_all_inputs_before_eval_and_build(self):
        result, lock, _, calls = self.run_install()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(lock), {"updated": True})
        commands = []
        for tool, *args in calls:
            if tool == "nix" and args[:1] == ["store"]:
                continue
            opts = {args[i + 1]: args[i + 2] for i, a in enumerate(args) if a == "--option"}
            self.assertEqual(opts["substitute"], "true")
            self.assertEqual(opts["substituters"], "https://cache.nixos.org")
            while args[:1] == ["--option"]:
                args = args[3:]
            commands.append(args[:2] if tool == "nix" else args[:1])
        self.assertEqual(commands, [["flake", "update"], ["eval", "--raw"], ["build"], ["switch"]])

    def test_failures_restore_previous_lock(self):
        for stage in ("update", "eval", "build", "switch"):
            with self.subTest(stage=stage):
                result, lock, original, _ = self.run_install(failure=stage)
                self.assertNotEqual(result.returncode, 0)
                self.assertEqual(lock, original)

    def test_cancelled_install_restores_previous_lock_without_switching(self):
        result, lock, original, calls = self.run_install(answer="n")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(lock, original)
        self.assertFalse(any(c[:2] == ["nixos-rebuild", "switch"] for c in calls))


if __name__ == "__main__":
    unittest.main()
