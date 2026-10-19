"""Use the real Nix CLI to catch argument-contract regressions in nx pull."""
import importlib.util
import json
import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

SPEC = importlib.util.spec_from_file_location("nx", Path(__file__).resolve().parents[1] / "pkgs/nx/nx.py")
nx = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(nx)


class RealNixTests(unittest.TestCase):
    def setUp(self):
        self.assertIsNotNone(shutil.which("nix"), "This CLI integration test requires Nix")
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        root = Path(self.tmp.name)
        self.repo = root / "checkout with spaces"
        self.repo.mkdir()
        self.keep, self.extra = root / "keep", root / "extra"
        for path in (self.keep, self.extra):
            path.mkdir()
            (path / "flake.nix").write_text('{ outputs = inputs: {}; }')
        self.flake = self.repo / "flake.nix"
        self.declaration = 'inputs.keep.url = ' + json.dumps('path:' + str(self.keep)) + ';'
        self.flake.write_text('{ ' + self.declaration + ' outputs = inputs: {}; }')
        config = os.environ.get("NIX_CONFIG", "") + '\nexperimental-features = nix-command flakes\naccept-flake-config = false\n'
        env = patch.dict(os.environ, {"NIX_CONFIG": config})
        env.start(); self.addCleanup(env.stop)
        subprocess.run(["nix", "flake", "lock", str(self.repo)], check=True, capture_output=True)
        self.text = (self.repo / "flake.lock").read_text()
        self.saved = json.loads(self.text)
        self.backup = root / "backup.lock"
        self.backup.write_text(self.text)

    def test_positional_flake_url_preserves_existing_pin_and_adds_missing_input(self):
        extra = 'inputs.extra.url = ' + json.dumps('path:' + str(self.extra)) + ';'
        self.flake.write_text('{ ' + self.declaration + extra + ' outputs = inputs: {}; }')
        nx.reconcile_local_lock(self.repo, self.text, self.backup)
        value = json.loads((self.repo / "flake.lock").read_text())
        old_edge = self.saved["nodes"][self.saved["root"]]["inputs"]["keep"]
        new_edge = value["nodes"][value["root"]]["inputs"]["keep"]
        self.assertEqual(value["nodes"][new_edge], self.saved["nodes"][old_edge])
        self.assertIn("extra", value["nodes"][value["root"]]["inputs"])
        self.assertEqual(self.backup.read_text(), self.text)

    def test_real_nix_failure_restores_lock_and_retains_backup(self):
        self.flake.write_text("{ deliberately invalid")
        with self.assertRaises(SystemExit):
            nx.reconcile_local_lock(self.repo, self.text, self.backup)
        self.assertEqual((self.repo / "flake.lock").read_text(), self.text)
        self.assertEqual(self.backup.read_text(), self.text)


if __name__ == "__main__":
    unittest.main()
