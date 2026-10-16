"""Unit tests for the pure logic of nx (no network, no Nix)."""
import importlib.util
import os
import tempfile
import unittest
from pathlib import Path

SPEC = importlib.util.spec_from_file_location("nx", Path(__file__).resolve().parents[1] / "pkgs/nx/nx.py")
nx = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(nx)

LOCK = {
    "root": "root",
    "nodes": {
        "root": {"inputs": {"nixpkgs": "nixpkgs_2", "mango": "mango", "pinned": "pinned", "hm": "hm"}},
        "nixpkgs_2": {
            "locked": {"rev": "aaa", "lastModified": 1},
            "original": {"type": "github", "owner": "NixOS", "repo": "nixpkgs", "ref": "nixos-unstable"},
        },
        "mango": {
            "inputs": {"nixpkgs": ["nixpkgs"]},
            "locked": {"rev": "bbb"},
            "original": {"type": "github", "owner": "mangowm", "repo": "mango"},
        },
        "pinned": {"locked": {"rev": "ccc"}, "original": {"type": "github", "owner": "a", "repo": "b", "rev": "ccc"}},
        "hm": {"inputs": {"nixpkgs": ["nixpkgs"]}, "locked": {"rev": "ddd"}, "original": {"type": "path", "path": "/x"}},
    },
}


class LockTests(unittest.TestCase):
    def test_follows_resolution(self):
        self.assertEqual(nx.resolve_node(LOCK, ["nixpkgs"]), "nixpkgs_2")

    def test_root_inputs(self):
        names = {r["name"]: r for r in nx.lock_inputs(LOCK)}
        self.assertEqual(set(names), {"nixpkgs", "mango", "pinned", "hm"})
        self.assertEqual(names["nixpkgs"]["locked"]["rev"], "aaa")
        self.assertFalse(names["mango"]["follows"])

    def test_remote_of(self):
        self.assertEqual(nx.remote_of(LOCK["nodes"]["mango"]["original"]),
                         ("https://github.com/mangowm/mango.git", "HEAD"))
        self.assertEqual(nx.remote_of(LOCK["nodes"]["nixpkgs_2"]["original"])[1], "nixos-unstable")
        self.assertIsNone(nx.remote_of(LOCK["nodes"]["pinned"]["original"]))
        self.assertIsNone(nx.remote_of(LOCK["nodes"]["hm"]["original"]))

    def test_check_rows(self):
        def fake(url, ref):
            if "mango" in url:
                raise RuntimeError("down")
            return "aaa" if "nixpkgs" in url else "zzz"

        rows = {r["name"]: r["status"] for r in nx.check_rows(nx.lock_inputs(LOCK), ls_remote=fake)}
        self.assertEqual(rows, {"nixpkgs": "current", "mango": "unreachable", "pinned": "pinned", "hm": "pinned"})

        def newer(url, ref):
            return "new"

        rows = {r["name"]: r["status"] for r in nx.check_rows(nx.lock_inputs(LOCK), ls_remote=newer)}
        self.assertEqual(rows["nixpkgs"], "update")
        self.assertEqual(rows["mango"], "update")

    def test_offline_never_calls_remote(self):
        def boom(url, ref):
            raise AssertionError("network used")

        rows = nx.check_rows(nx.lock_inputs(LOCK), ls_remote=boom, offline=True)
        self.assertEqual({r["status"] for r in rows if r["name"] in ("nixpkgs", "mango")}, {"offline"})

    def test_lock_summary(self):
        new = {**LOCK, "nodes": {**LOCK["nodes"], "mango": {**LOCK["nodes"]["mango"], "locked": {"rev": "eeeeeeeeeeee"}}}}
        lines = nx.lock_summary(LOCK, new)
        self.assertEqual(len(lines), 1)
        self.assertIn("mango", lines[0])
        self.assertIn("bbb -> eeeeeeee", lines[0])


class GenerationTests(unittest.TestCase):
    def make_profiles(self, count):
        tmp = tempfile.TemporaryDirectory()
        root = Path(tmp.name)
        for number in range(1, count + 1):
            store = root / f"store-{number}"
            store.mkdir()
            (store / "nixos-version").write_text(f"26.11.{number}")
            os.symlink(store, root / f"system-{number}-link")
        return tmp, root

    def test_listing_and_flags(self):
        tmp, root = self.make_profiles(4)
        with tmp:
            gens = nx.list_generations(root, selected=str((root / "store-4").resolve()),
                                       running=str((root / "store-3").resolve()),
                                       booted=str((root / "store-2").resolve()))
            self.assertEqual([g["number"] for g in gens], [4, 3, 2, 1])
            flags = {g["number"]: (g["selected"], g["running"], g["booted"]) for g in gens}
            self.assertEqual(flags[4], (True, False, False))
            self.assertEqual(flags[3], (False, True, False))
            self.assertEqual(flags[2], (False, False, True))
            self.assertEqual(gens[0]["version"], "26.11.4")

    def test_clean_keeps_newest_and_protected(self):
        gens = [{"number": n, "selected": n == 10, "running": n == 8, "booted": n == 2} for n in range(10, 0, -1)]
        # keep=3 -> newest 4 (10..7) plus running 8 and booted 2
        self.assertEqual(nx.select_deletions(gens, 3), [1, 3, 4, 5, 6])
        self.assertEqual(nx.select_deletions(gens, 20), [])

    def test_clean_never_deletes_protected(self):
        gens = [{"number": n, "selected": False, "running": n == 1, "booted": False} for n in range(5, 0, -1)]
        self.assertNotIn(1, nx.select_deletions(gens, 0))


if __name__ == "__main__":
    unittest.main()
