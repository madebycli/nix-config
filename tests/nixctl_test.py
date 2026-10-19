"""Exercise the real nixctl script against a temporary repository and fake commands."""
import json
import os
import shlex
import subprocess
import tempfile
import unittest
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[1] / "pkgs/nixctl/nixctl.sh"


class NixctlTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.repo = self.root / "checkout with spaces"
        self.file = self.repo / "hosts/nyx/features.nix"
        self.file.parent.mkdir(parents=True)
        self.original = '''{\n  my.kernel = "latest"; # keep this\n  my.desktop.compositors = [ "mango" ];\n  my.desktop.defaultSession = "mango";\n  my.desktop.shell = "noctalia";\n  my.features.gaming.enable = true;\n  my.features.ai.enable = false;\n}\n'''
        self.file.write_text(self.original)
        conf = self.root / "nixctl.conf"
        conf.write_text(f"REPO={shlex.quote(str(self.repo))}\nHOST=nyx\n")
        self.log = self.root / "calls.jsonl"
        bindir = self.root / "bin"
        bindir.mkdir()
        for name in ("gum", "nixos-rebuild", "sudo", "nix"):
            executable = bindir / name
            executable.write_text('''#!/usr/bin/env python3
import json,os,sys
from pathlib import Path
name=Path(sys.argv[0]).name
with open(os.environ['CALL_LOG'],'a') as f: f.write(json.dumps([name,*sys.argv[1:]])+'\\n')
if name=='gum':
 if sys.argv[1]=='choose':
  if os.environ.get('CANCEL'): sys.exit(130)
  print(os.environ.get('CHOICE','latest'))
 else: sys.exit(1)
if name=='nixos-rebuild' and os.environ.get('FAIL_BUILD'): sys.exit(1)
''')
            executable.chmod(0o755)
        self.env = dict(os.environ, PATH=str(bindir) + os.pathsep + os.environ["PATH"], NIXCTL_CONF=str(conf), CALL_LOG=str(self.log))

    def run_cli(self, *args, **env):
        return subprocess.run(["bash", "-euo", "pipefail", str(SCRIPT), *args], env=dict(self.env, **env), text=True, capture_output=True)

    def calls(self):
        return [json.loads(line) for line in self.log.read_text().splitlines()] if self.log.exists() else []

    def test_kernel_changes_only_its_one_line_and_declining_keeps_activation_off(self):
        result = self.run_cli("kernel", "cachyos")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.file.read_text(), self.original.replace('"latest"', '"cachyos"'))
        self.assertTrue(all(c[0] == "gum" for c in self.calls()))

    def test_cancelled_kernel_menu_does_not_edit_the_file(self):
        result = self.run_cli("kernel", CANCEL="1")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.file.read_text(), self.original)

    def test_unknown_kernel_or_regex_feature_cannot_modify_other_settings(self):
        for args in (("kernel", "evil"), ("on", ".*"), ("off", "gaming|ai")):
            result = self.run_cli(*args)
            self.assertNotEqual(result.returncode, 0)
            self.assertEqual(self.file.read_text(), self.original)

    def test_gaming_switch_keeps_desktop_and_kernel_unchanged(self):
        result = self.run_cli("off", "gaming")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.file.read_text(), self.original.replace('gaming.enable = true;', 'gaming.enable = false;'))
        self.assertEqual(self.calls(), [])

    def test_failed_build_stops_before_confirmation_or_activation(self):
        result = self.run_cli("apply", FAIL_BUILD="1")
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual([c[0] for c in self.calls()], ["nixos-rebuild"])
        self.assertIn(str(self.repo) + "#nyx", self.calls()[0])


if __name__ == "__main__":
    unittest.main()
