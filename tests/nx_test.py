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


class ProfileTests(unittest.TestCase):
    ELEMENTS = {
        "hello": {"originalUrl": "github:owner/hello", "url": "github:owner/hello/" + "a" * 40,
                  "attrPath": "packages.x86_64-linux.hello", "active": True,
                  "storePaths": ["/nix/store/" + "a" * 32 + "-hello-1.0"]},
        "local-tool": {"originalUrl": "path:/work/tools with spaces", "url": "path:/locked/tools",
                       "attrPath": "packages.x86_64-linux.default",
                       "storePaths": ["/nix/store/" + "b" * 32 + "-local-tool-2.0"]},
        "gitlab-tool": {"originalUrl": "gitlab:owner/tool", "url": "gitlab:owner/tool/" + "c" * 40,
                        "storePaths": ["/nix/store/" + "c" * 32 + "-gitlab-tool-3.0"]},
        "store-tool": {"storePaths": ["/nix/store/" + "d" * 32 + "-store-tool-4.0"]},
    }

    def invoke(self, argv, elements=None, confirm=True, failure=None, raw=None):
        calls = []

        def execute(command, **kwargs):
            calls.append(command)
            self.assertEqual(command[:2], ["nix", "profile"], "profile-only operation escaped its scope")
            action = command[2]
            if action == "list":
                payload = {"elements": self.ELEMENTS if elements is None else elements}
                stdout = json.dumps(payload) if raw is None else raw
            elif action == "history":
                stdout = "Version 2: hello: 1.0 -> 2.0\n"
            else:
                stdout = ""
            return subprocess.CompletedProcess(command, 23 if action == failure else 0,
                                               stdout=stdout, stderr="fixture failure" if action == failure else "")

        output = io.StringIO()
        with mock.patch.object(nx.subprocess, "run", side_effect=execute), \
                mock.patch.object(nx, "load_conf", side_effect=AssertionError("read system config")), \
                mock.patch.object(nx, "build_system", side_effect=AssertionError("built system")), \
                mock.patch.object(nx, "activate", side_effect=AssertionError("activated system")), \
                mock.patch.object(nx, "confirm", return_value=confirm) as confirmation, \
                contextlib.redirect_stdout(output), contextlib.redirect_stderr(io.StringIO()):
            try:
                result = nx.main(argv)
            finally:
                self.calls, self.confirmation = calls, confirmation
        self.assertEqual(result, 0)
        return output.getvalue()

    def test_default_list_includes_every_source_and_needs_no_system_config(self):
        result = json.loads(self.invoke(["profiles", "--json"]))
        self.assertEqual(result["profile"], None)
        packages = {p["name"]: p for p in result["packages"]}
        self.assertEqual(set(packages), set(self.ELEMENTS))
        self.assertEqual(packages["hello"]["package"], "hello-1.0")
        self.assertIsNone(packages["store-tool"]["original_url"])
        self.assertEqual(self.calls, [["nix", "profile", "list", "--json"]])
        self.confirmation.assert_not_called()

    def test_indexed_manifest_is_supported(self):
        rows = json.loads(self.invoke(["profiles", "list", "--json"], elements=list(self.ELEMENTS.values())))
        self.assertEqual([p["name"] for p in rows["packages"]], ["0", "1", "2", "3"])

    def test_older_uri_fields_are_preserved(self):
        rows = json.loads(self.invoke(["profiles", "--json"], elements=[{
            "originalUri": "gitlab:owner/tool", "uri": "gitlab:owner/tool/locked", "storePaths": []}]))
        self.assertEqual(rows["packages"][0]["original_url"], "gitlab:owner/tool")

    def test_profile_option_works_before_and_after_subcommand(self):
        for argv in (["profiles", "--profile", "/work/profile with spaces", "list", "--json"],
                     ["profiles", "list", "--profile", "/work/profile with spaces", "--json"]):
            with self.subTest(argv=argv):
                data = json.loads(self.invoke(argv))
                self.assertEqual(data["profile"], "/work/profile with spaces")
                self.assertEqual(self.calls[0], ["nix", "profile", "list", "--profile", "/work/profile with spaces", "--json"])

    def test_profile_only_update_is_independent_and_updates_all_sources(self):
        output = self.invoke(["update", "profiles", "--profile", "/work/profile", "--yes"])
        self.assertEqual(self.calls[-1], ["nix", "profile", "upgrade", "--profile", "/work/profile",
                                         "--all", "--refresh", "--no-write-lock-file"])
        self.assertIn("store-tool", output)
        self.assertTrue(self.confirmation.call_args.args[1])

    def test_empty_profile_update_does_not_mutate_or_prompt(self):
        self.assertIn("No packages", self.invoke(["update", "profiles"], elements={}))
        self.assertEqual(len(self.calls), 1)
        self.confirmation.assert_not_called()

    def test_update_can_select_an_exact_package(self):
        self.invoke(["profiles", "update", "gitlab-tool", "--yes"])
        self.assertEqual(self.calls[-1], ["nix", "profile", "upgrade", "gitlab-tool", "--refresh", "--no-write-lock-file"])

    def test_remove_validates_every_name_before_mutating(self):
        with self.assertRaises(SystemExit):
            self.invoke(["profiles", "remove", "hello", "missing", "--yes"])
        self.assertEqual(len(self.calls), 1)
        self.confirmation.assert_not_called()

    def test_remove_uses_exact_names_and_separate_arguments(self):
        self.invoke(["profiles", "remove", "hello", "local-tool", "hello", "--yes"])
        self.assertEqual(self.calls[-1], ["nix", "profile", "remove", "hello", "local-tool"])

    def test_remove_rejects_wildcards_and_option_injection(self):
        for value in ("*", "--all", "--profile"):
            with self.subTest(value=value), self.assertRaises(SystemExit):
                self.invoke(["profiles", "remove", "--yes", "--", value])
            self.assertEqual(len(self.calls), 1)

    def test_cancelled_profile_mutations_do_not_run(self):
        for argv in (["profiles", "remove", "hello"], ["profiles", "update"],
                     ["update", "profiles"], ["profiles", "install", "nixpkgs#hello"],
                     ["profiles", "rollback"]):
            with self.subTest(argv=argv):
                self.invoke(argv, confirm=False)
                self.assertTrue(all(call[2] == "list" for call in self.calls))

    def test_install_preserves_local_paths_without_writing_source_locks(self):
        self.invoke(["profiles", "--profile", "/work/profile", "add", "path:/work/tool with spaces#hello", "--yes"])
        self.assertEqual(self.calls, [["nix", "profile", "install", "--profile", "/work/profile",
                                      "path:/work/tool with spaces#hello", "--no-write-lock-file"]])

    def test_install_rejects_option_injection(self):
        with self.assertRaises(SystemExit):
            self.invoke(["profiles", "install", "--yes", "--", "--impure"])
        self.assertEqual(self.calls, [])

    def test_history_json_preserves_native_history(self):
        result = json.loads(self.invoke(["profiles", "history", "--json"]))
        self.assertIn("hello: 1.0 -> 2.0", result["history"])
        self.assertEqual(self.calls, [["nix", "profile", "history"]])

    def test_rollback_can_target_a_profile_generation(self):
        self.invoke(["profiles", "rollback", "7", "--profile", "/work/profile", "--yes"])
        self.assertEqual(self.calls[-1], ["nix", "profile", "rollback", "--profile", "/work/profile", "--to", "7"])

    def test_nonpositive_rollback_generation_is_rejected(self):
        with self.assertRaises(SystemExit):
            self.invoke(["profiles", "rollback", "0", "--yes"])
        self.assertEqual(self.calls, [])

    def test_failed_list_is_not_reported_as_an_empty_profile(self):
        with self.assertRaises(SystemExit):
            self.invoke(["profiles", "--json"], failure="list")

    def test_invalid_json_is_an_error(self):
        for value in ("garbage", "[]", '{"elements":null}'):
            with self.subTest(value=value), self.assertRaises(SystemExit):
                self.invoke(["profiles", "--json"], raw=value)

    def test_upgrade_failure_is_not_reported_as_success(self):
        with self.assertRaises(SystemExit):
            self.invoke(["update", "profiles", "--yes"], failure="upgrade")

    def test_profile_only_update_rejects_system_flags_before_any_action(self):
        for flag in ("--boot", "--build", "--commit", "--push"):
            with self.subTest(flag=flag), self.assertRaises(SystemExit):
                self.invoke(["update", "profiles", flag, "--yes"])
            self.assertEqual(self.calls, [])

    def test_system_update_requires_explicit_profile_scope_for_profile_path(self):
        with self.assertRaises(SystemExit):
            self.invoke(["update", "--profile", "/work/profile", "--yes"])
        self.assertEqual(self.calls, [])


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
                self.assertEqual(cmd, ["nix", "flake", "lock", str(self.repo)])
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

    def update(self, options=(), fail_build=False, fail_identity=False, interrupt=False,
               profile_packages=(), fail_profile=False):
        calls = []
        real_subprocess_run = subprocess.run

        def run(cmd, **kwargs):
            if cmd[0] == "nix":
                calls.append(cmd)
                if cmd[1:3] == ["profile", "upgrade"]:
                    return subprocess.CompletedProcess(cmd, 23 if fail_profile else 0)
                self.assertEqual(cmd[1:3], ["flake", "update"])
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
                mock.patch.object(nx, "profile_packages", return_value=list(profile_packages)), \
                mock.patch.object(nx, "require_git_identity", identity), \
                mock.patch.object(nx.subprocess, "run", side_effect=run), \
                mock.patch.object(nx, "build_system", return_value=None if fail_build else "/nix/store/test"), \
                mock.patch.object(nx, "show_diff"), mock.patch.object(nx, "confirm", return_value=True) as confirmation, \
                mock.patch.object(nx, "activate") as activate, \
                contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            try:
                nx.cmd_update(args)
            finally:
                self.last_update_calls, self.last_identity, self.last_activate = calls, identity, activate
                self.last_confirmation = confirmation
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

    def test_combined_update_covers_all_profile_sources_with_one_confirmation(self):
        self.update(["--profiles", "--profile", "/work/profile with spaces"],
                    profile_packages=[{"name": "gitlab-tool"}, {"name": "local-tool"}])
        self.assertEqual(self.last_update_calls[-1],
                         ["nix", "profile", "upgrade", "--profile", "/work/profile with spaces",
                          "--all", "--refresh", "--no-write-lock-file"])
        self.last_activate.assert_called_once()
        self.assertEqual(self.last_confirmation.call_count, 1)

    def test_profile_failure_after_system_activation_is_reported_without_rolling_back_lock(self):
        saved = self.local_lock()
        with self.assertRaises(SystemExit):
            self.update(["--profiles"], profile_packages=[{"name": "local-tool"}], fail_profile=True)
        self.last_activate.assert_called_once()
        self.assertNotEqual((self.repo / "flake.lock").read_text(), saved)


if __name__ == "__main__":
    unittest.main()
