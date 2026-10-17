"""nx logic and local Git workflow tests (no network or system activation)."""
import contextlib
import importlib.util
import io
import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock

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


class WorkflowTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.env = mock.patch.dict(os.environ, {
            "GIT_CONFIG_GLOBAL": os.devnull, "GIT_CONFIG_NOSYSTEM": "1",
            "GIT_AUTHOR_NAME": "test", "GIT_AUTHOR_EMAIL": "test@example.invalid",
            "GIT_COMMITTER_NAME": "test", "GIT_COMMITTER_EMAIL": "test@example.invalid",
        })
        self.env.start()
        self.addCleanup(self.env.stop)
        self.remote, self.seed, self.repo = (self.root / n for n in ("remote.git", "seed", "repo"))
        self.git(self.root, "init", "--bare", "-q", "-b", "main", str(self.remote))
        self.git(self.root, "clone", "-q", str(self.remote), str(self.seed))
        (self.seed / "flake.lock").write_text(json.dumps(LOCK, indent=2) + "\n")
        (self.seed / "flake.nix").write_text("old declarations\n")
        (self.seed / "other.txt").write_text("base\n")
        self.git(self.seed, "add", ".")
        self.git(self.seed, "commit", "-qm", "base")
        self.git(self.seed, "push", "-q", "origin", "main")
        self.git(self.root, "clone", "-q", str(self.remote), str(self.repo))

    def git(self, repo, *args):
        return subprocess.run(["git", "-C", str(repo), *args], check=True,
                              capture_output=True, text=True).stdout.strip()

    def local_lock(self, staged=False):
        data = json.loads((self.repo / "flake.lock").read_text())
        data["nodes"]["nixpkgs_2"]["locked"]["rev"] = "local-newer"
        text = json.dumps(data, indent=2) + "\n"
        (self.repo / "flake.lock").write_text(text)
        if staged:
            self.git(self.repo, "add", "flake.lock")
        return text

    def incoming(self, conflict=False):
        data = json.loads((self.seed / "flake.lock").read_text())
        data["nodes"]["nixpkgs_2"]["locked"]["rev"] += "-remote"
        (self.seed / "flake.lock").write_text(json.dumps(data, indent=2) + "\n")
        (self.seed / "flake.nix").write_text("new declarations\n")
        if conflict:
            (self.seed / "other.txt").write_text("remote\n")
            (self.repo / "other.txt").write_text("local\n")
        self.git(self.seed, "add", ".")
        self.git(self.seed, "commit", "-qm", "upstream changes")
        self.git(self.seed, "push", "-q", "origin", "main")

    def pull(self, fail_nix=False):
        real_run = nx.run
        calls = []

        def run(cmd, **kwargs):
            if cmd[0] == "nix":
                calls.append(cmd)
                self.assertEqual(cmd[:3], ["nix", "flake", "lock"])
                data = json.loads((self.repo / "flake.lock").read_text())
                self.assertEqual(data["nodes"]["nixpkgs_2"]["locked"]["rev"], "local-newer")
                self.assertEqual((self.repo / "flake.nix").read_text(), "new declarations\n")
                data["nodes"]["mango"]["locked"]["rev"] = "reconciled"
                (self.repo / "flake.lock").write_text(json.dumps(data))
                return subprocess.CompletedProcess(cmd, 1 if fail_nix else 0)
            return real_run(cmd, **(kwargs | {"capture": True}))

        with mock.patch.object(nx, "load_conf", return_value=(self.repo, "nyx")), \
                mock.patch.object(nx, "run", side_effect=run), \
                contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            nx.cmd_pull(None)
        return calls

    def test_pull_preserves_local_lock_and_reconciles_new_declarations(self):
        saved = self.local_lock()
        self.incoming()
        self.assertEqual(len(self.pull()), 1)
        data = json.loads((self.repo / "flake.lock").read_text())
        self.assertEqual(data["nodes"]["nixpkgs_2"]["locked"]["rev"], "local-newer")
        self.assertEqual(data["nodes"]["mango"]["locked"]["rev"], "reconciled")
        self.assertEqual(self.git(self.repo, "rev-parse", "HEAD"), self.git(self.seed, "rev-parse", "HEAD"))
        self.assertEqual(self.git(self.repo, "diff", "--name-only", "--diff-filter=U"), "")
        self.assertEqual(self.git(self.repo, "stash", "list"), "")
        backups = list((self.repo / ".git/nx/lock-backups").glob("*.lock"))
        self.assertEqual([p.read_text() for p in backups], [saved])

    def test_pull_handles_staged_local_lock(self):
        self.local_lock(staged=True)
        self.incoming()
        self.pull()
        self.assertEqual(self.git(self.repo, "diff", "--cached", "--name-only"), "")
        self.assertIn("flake.lock", self.git(self.repo, "diff", "--name-only"))

    def test_update_then_pull_can_repeat_without_lock_conflicts(self):
        self.local_lock()
        for _ in range(2):
            self.update()
            self.incoming()
            self.pull()
            self.assertEqual(self.git(self.repo, "diff", "--name-only", "--diff-filter=U"), "")
            self.assertEqual(self.git(self.repo, "stash", "list"), "")

    def test_clean_lock_follows_remote_without_reconciliation(self):
        self.incoming()
        self.assertEqual(self.pull(), [])
        self.assertEqual(self.git(self.repo, "status", "--porcelain"), "")

    def test_failed_reconciliation_restores_exact_local_lock(self):
        saved = self.local_lock()
        self.incoming()
        with self.assertRaises(SystemExit):
            self.pull(fail_nix=True)
        self.assertEqual((self.repo / "flake.lock").read_text(), saved)
        self.assertEqual(self.git(self.repo, "diff", "--name-only", "--diff-filter=U"), "")

    def test_other_autostash_conflicts_are_reported_as_failure(self):
        saved = self.local_lock()
        self.incoming(conflict=True)
        with self.assertRaises(SystemExit):
            self.pull()
        self.assertEqual((self.repo / "flake.lock").read_text(), saved)
        self.assertEqual(self.git(self.repo, "diff", "--name-only", "--diff-filter=U"), "other.txt")
        self.assertTrue(self.git(self.repo, "stash", "list"))

    def update(self, options=(), fail_build=False, fail_identity=False, interrupt=False):
        calls = []
        real_subprocess_run = subprocess.run

        def run(cmd, **kwargs):
            if cmd[0] == "nix":
                calls.append(cmd)
                data = json.loads((self.repo / "flake.lock").read_text())
                data["nodes"]["mango"]["locked"]["rev"] += "-updated"
                (self.repo / "flake.lock").write_text(json.dumps(data))
                if interrupt:
                    raise KeyboardInterrupt()
                return subprocess.CompletedProcess(cmd, 0)
            return real_subprocess_run(cmd, **kwargs)

        identity = mock.Mock(side_effect=SystemExit(1) if fail_identity else None)
        args = nx.build_parser().parse_args(["update", *options])
        with mock.patch.object(nx, "load_conf", return_value=(self.repo, "nyx")), \
                mock.patch.object(nx, "profile_rows", return_value=[]), \
                mock.patch.object(nx, "require_git_identity", identity), \
                mock.patch.object(nx.subprocess, "run", side_effect=run), \
                mock.patch.object(nx, "build_system", return_value=None if fail_build else "/nix/store/test"), \
                mock.patch.object(nx, "show_diff"), mock.patch.object(nx, "confirm", return_value=True), \
                mock.patch.object(nx, "activate") as activate, \
                contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            try:
                nx.cmd_update(args)
            finally:
                self.last_update_calls, self.last_identity, self.last_activate = calls, identity, activate
        return calls, identity

    def test_repeated_updates_refresh_all_inputs_without_commits_or_identity(self):
        self.local_lock()
        head = self.git(self.repo, "rev-parse", "HEAD")
        for _ in range(2):
            calls, identity = self.update()
            self.assertEqual(len(calls), 1)
            self.assertEqual(calls[0][:3], ["nix", "flake", "update"])
            self.assertEqual(set(calls[0][3:-2]), {"nixpkgs", "mango", "pinned", "hm"})
            identity.assert_not_called()
            self.assertEqual(self.git(self.repo, "rev-parse", "HEAD"), head)

    def test_update_failure_restores_existing_local_changes(self):
        saved = self.local_lock()
        with self.assertRaises(SystemExit):
            self.update(fail_build=True)
        self.assertEqual((self.repo / "flake.lock").read_text(), saved)
        self.last_activate.assert_not_called()

    def test_explicit_commit_checks_identity_before_updating_or_activating(self):
        saved = self.local_lock()
        with self.assertRaises(SystemExit):
            self.update(["--commit"], fail_identity=True)
        self.assertEqual(self.last_update_calls, [])
        self.last_activate.assert_not_called()
        self.assertEqual((self.repo / "flake.lock").read_text(), saved)

    def test_interrupt_restores_existing_local_lock_before_activation(self):
        saved = self.local_lock()
        with self.assertRaises(KeyboardInterrupt):
            self.update(interrupt=True)
        self.last_activate.assert_not_called()
        self.assertEqual((self.repo / "flake.lock").read_text(), saved)

    def test_build_only_needs_no_identity_and_restores_local_lock(self):
        saved = self.local_lock()
        _, identity = self.update(["--build", "--commit"])
        identity.assert_not_called()
        self.last_activate.assert_not_called()
        self.assertEqual((self.repo / "flake.lock").read_text(), saved)


if __name__ == "__main__":
    unittest.main()
