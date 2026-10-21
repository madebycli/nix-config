"""Real Nix profile lifecycle in a disposable profile, without network or sudo."""
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from urllib.parse import quote


NX = Path(__file__).resolve().parents[1] / "pkgs/nx/nx.py"
FLAKE = r'''
{
  outputs = { self }: {
    packages.x86_64-linux = let
      package = name: version: builtins.derivation {
        name = "nx-fixture-${name}-${version}";
        system = "x86_64-linux";
        builder = "/bin/sh";
        args = [ "-c" "/bin/mkdir -p \"$out/bin\"; printf fixture > \"$out/bin/${name}\"" ];
      };
    in {
      hello = package "hello" "HELLO_VERSION";
      world = package "world" "1";
    };
  };
}
'''


class RealProfileTests(unittest.TestCase):
    def setUp(self):
        self.assertIsNotNone(shutil.which("nix"), "This CLI integration test requires Nix")
        self.tmp = tempfile.TemporaryDirectory(prefix="nx-profile-cli-")
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.source = self.root / "flake with spaces"
        self.source.mkdir()
        self.profile = self.root / "profile with spaces"
        self.write_flake("1")
        # Only this disposable fixture permits a /bin/sh builder and disables
        # substitution. Production cache/sandbox settings are not modified.
        config = os.environ.get("NIX_CONFIG", "") + (
            "\nexperimental-features = nix-command flakes\n"
            "accept-flake-config = false\nsandbox = false\nsubstitute = false\n"
        )
        self.env = {**os.environ, "NIX_CONFIG": config,
                    "NX_CONF": str(self.root / "nonexistent-nixctl.conf"),
                    "XDG_CACHE_HOME": str(self.root / "cache")}

    def write_flake(self, version):
        (self.source / "flake.nix").write_text(FLAKE.replace("HELLO_VERSION", version))

    def nx(self, *args, success=True):
        result = subprocess.run([sys.executable, str(NX), *map(str, args)],
                                env=self.env, cwd=self.root, capture_output=True, text=True)
        if success:
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        else:
            self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)
        return result

    def packages(self):
        data = json.loads(self.nx("profiles", "list", "--profile", self.profile, "--json").stdout)
        return {p["name"]: p for p in data["packages"]}

    def install(self, attribute):
        self.nx("profiles", "--profile", self.profile, "install",
                f"path:{quote(str(self.source), safe='/')}#{attribute}", "--yes")

    def test_install_profile_only_update_remove_history_and_rollback(self):
        self.assertEqual(self.packages(), {})
        self.install("hello")
        initial = self.packages()
        self.assertEqual(len(initial), 1)
        hello = next(iter(initial))
        self.assertIn("hello-1", initial[hello]["package"])
        self.assertFalse((self.source / "flake.lock").exists())

        self.write_flake("2")
        source_before = (self.source / "flake.nix").read_bytes()
        self.nx("update", "profiles", "--profile", self.profile, "--yes")
        updated = self.packages()
        self.assertNotEqual(initial[hello]["store_paths"], updated[hello]["store_paths"])
        self.assertIn("hello-2", updated[hello]["package"])
        self.assertEqual((self.source / "flake.nix").read_bytes(), source_before)
        self.assertFalse((self.source / "flake.lock").exists())

        self.install("world")
        both = self.packages()
        self.assertEqual(len(both), 2)
        refused = self.nx("profiles", "remove", hello, "--profile", self.profile, success=False)
        self.assertIn("confirmation needed", refused.stderr)
        self.assertEqual(self.packages(), both)

        self.nx("profiles", "remove", hello, "--profile", self.profile, "--yes")
        self.assertNotIn(hello, self.packages())
        self.assertEqual(len(self.packages()), 1)
        history = json.loads(self.nx("profiles", "history", "--profile", self.profile, "--json").stdout)
        self.assertTrue(history["history"].strip())

        self.nx("profiles", "rollback", "--profile", self.profile, "--yes")
        self.assertEqual(self.packages(), both)

    def test_empty_profile_update_leaves_generation_unchanged(self):
        self.install("hello")
        name = next(iter(self.packages()))
        self.nx("profiles", "remove", name, "--profile", self.profile, "--yes")
        self.assertEqual(self.packages(), {})
        generation = os.readlink(self.profile)
        output = self.nx("update", "profiles", "--profile", self.profile).stdout
        self.assertIn("No packages", output)
        self.assertEqual(os.readlink(self.profile), generation)


if __name__ == "__main__":
    unittest.main()
