from __future__ import annotations

import argparse
import builtins
import importlib.util
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from types import ModuleType
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]


def load_script(name: str, filename: str) -> ModuleType:
    path = ROOT / "scripts" / filename
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def command(*args: str, cwd: Path | None = None) -> str:
    return subprocess.run(
        list(args),
        cwd=cwd,
        check=True,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    ).stdout.strip()


def configure_identity(repo: Path) -> None:
    command("git", "config", "user.name", "Sync Test", cwd=repo)
    command("git", "config", "user.email", "sync-test@example.invalid", cwd=repo)


class GitHubAuthTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.auth = load_script("nix_config_github_auth_test", "github-cli-auth.py")

    def test_missing_gh_is_explicit_and_token_free(self) -> None:
        with (
            mock.patch.object(self.auth.shutil, "which", return_value=None),
            mock.patch.object(
                self.auth,
                "git",
                side_effect=lambda _repo, *args, **_kwargs: {
                    ("remote", "get-url", "origin"): self.auth.HTTPS_REMOTE,
                    ("config", "user.name"): "madebycli",
                    ("config", "user.email"): "example@users.noreply.github.com",
                }.get(tuple(args), ""),
            ),
        ):
            value = self.auth.status(Path("/tmp/repo"))
        self.assertFalse(value.gh_installed)
        self.assertFalse(value.authenticated)
        self.assertIn("gh", value.error or "")
        self.assertFalse(any("token" in key.lower() for key in value.__dataclass_fields__))

    def test_prepare_normalizes_known_ssh_remote_and_configures_git(self) -> None:
        initial = self.auth.AuthStatus(
            True,
            True,
            "madebycli",
            "ADMIN",
            True,
            "git@github.com:madebycli/nix-config.git",
            True,
            None,
            None,
            False,
            None,
        )
        final = self.auth.AuthStatus(
            True,
            True,
            "madebycli",
            "ADMIN",
            True,
            self.auth.HTTPS_REMOTE,
            True,
            "madebycli",
            "312612246+madebycli@users.noreply.github.com",
            True,
            None,
        )
        calls: list[tuple[str, ...]] = []

        def fake_run(args, *, cwd=None, check=False):
            calls.append(tuple(args))
            return subprocess.CompletedProcess(args, 0, stdout="", stderr="")

        with (
            mock.patch.object(self.auth, "status", side_effect=[initial, final]),
            mock.patch.object(self.auth, "run", side_effect=fake_run),
            mock.patch.object(self.auth, "_configure_identity"),
        ):
            result = self.auth.prepare(Path("/tmp/repo"), require_push=True)

        self.assertEqual(result.remote_url, self.auth.HTTPS_REMOTE)
        self.assertIn(
            ("git", "remote", "set-url", "origin", self.auth.HTTPS_REMOTE), calls
        )
        self.assertIn(
            ("gh", "auth", "setup-git", "--hostname", "github.com"), calls
        )

    def test_prepare_rejects_account_without_write_permission(self) -> None:
        status = self.auth.AuthStatus(
            True,
            True,
            "someone",
            "READ",
            False,
            self.auth.HTTPS_REMOTE,
            True,
            "someone",
            "someone@users.noreply.github.com",
            True,
            None,
        )
        with (
            mock.patch.object(self.auth, "status", side_effect=[status, status]),
            mock.patch.object(
                self.auth,
                "run",
                return_value=subprocess.CompletedProcess([], 0, stdout="", stderr=""),
            ),
            mock.patch.object(self.auth, "_configure_identity"),
        ):
            with self.assertRaises(self.auth.AuthError):
                self.auth.prepare(Path("/tmp/repo"), require_push=True)


class SyncBlackBoxTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.sync = load_script("nix_config_sync_blackbox_test", "config-sync.py")

    def make_remote_pair(self, root: Path) -> tuple[Path, Path]:
        bare = root / "remote.git"
        command("git", "init", "--bare", str(bare))
        local = root / "local"
        command("git", "clone", str(bare), str(local))
        configure_identity(local)
        (local / "flake.nix").write_text("initial\n", encoding="utf-8")
        command("git", "add", "flake.nix", cwd=local)
        command("git", "commit", "-m", "initial", cwd=local)
        command("git", "push", "-u", "origin", "HEAD", cwd=local)

        producer = root / "producer"
        command("git", "clone", str(bare), str(producer))
        configure_identity(producer)
        return local, producer

    def test_fast_forward_keeps_disjoint_local_change(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            local, producer = self.make_remote_pair(root)
            (local / "local-only.txt").write_text("keep me\n", encoding="utf-8")
            (producer / "remote-only.txt").write_text("download me\n", encoding="utf-8")
            command("git", "add", "remote-only.txt", cwd=producer)
            command("git", "commit", "-m", "remote", cwd=producer)
            command("git", "push", cwd=producer)

            _head, changed = self.sync.fast_forward(local, offline=False)

            self.assertIn("remote-only.txt", changed)
            self.assertEqual((local / "local-only.txt").read_text(), "keep me\n")
            self.assertEqual((local / "remote-only.txt").read_text(), "download me\n")

    def test_fast_forward_blocks_overlapping_local_change(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            local, producer = self.make_remote_pair(root)
            (local / "flake.nix").write_text("local edit\n", encoding="utf-8")
            (producer / "flake.nix").write_text("remote edit\n", encoding="utf-8")
            command("git", "add", "flake.nix", cwd=producer)
            command("git", "commit", "-m", "remote", cwd=producer)
            command("git", "push", cwd=producer)

            with self.assertRaises(self.sync.SyncError):
                self.sync.fast_forward(local, offline=False)
            self.assertEqual((local / "flake.nix").read_text(), "local edit\n")

    def test_command_pull_allows_disjoint_nixos_worktree_change(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            local, producer = self.make_remote_pair(root)
            (local / "local-only.txt").write_text("keep me\n", encoding="utf-8")
            (producer / "remote-only.txt").write_text("download me\n", encoding="utf-8")
            command("git", "add", "remote-only.txt", cwd=producer)
            command("git", "commit", "-m", "remote", cwd=producer)
            command("git", "push", cwd=producer)
            args = argparse.Namespace(
                repo=str(local),
                offline=False,
                scope="nixos",
                no_apply=True,
                profile=None,
                yes=True,
            )
            with mock.patch.object(self.sync, "ensure_remote"):
                self.sync.command_pull(args)
            self.assertEqual((local / "local-only.txt").read_text(), "keep me\n")
            self.assertEqual((local / "remote-only.txt").read_text(), "download me\n")

    def test_dotfiles_upload_copies_home_commits_and_saves_baseline(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            repo = root / "repo"
            home = root / "home"
            command("git", "init", str(repo))
            configure_identity(repo)
            (repo / "sync").mkdir(parents=True)
            (repo / "config/home").mkdir(parents=True)
            (repo / "flake.nix").write_text("initial\n", encoding="utf-8")
            (repo / "sync/paths.conf").write_text(".config/example\n", encoding="utf-8")
            (repo / "sync/excludes.conf").write_text("**/*.tmp\n", encoding="utf-8")
            command("git", "add", ".", cwd=repo)
            command("git", "commit", "-m", "initial", cwd=repo)

            active_dir = home / ".config/example"
            active_dir.mkdir(parents=True)
            (active_dir / "settings.conf").write_text("enabled=true\n", encoding="utf-8")
            args = argparse.Namespace(
                repo=str(repo),
                offline=True,
                scope="dotfiles",
                message=None,
                no_commit=False,
                profile=None,
                yes=True,
            )

            with (
                mock.patch.dict(os.environ, {"HOME": str(home)}, clear=False),
                mock.patch.object(self.sync, "ensure_remote"),
                mock.patch.object(
                    builtins,
                    "input",
                    side_effect=AssertionError("input must not be called"),
                ),
            ):
                self.sync.command_push(args)
                active, mirror, baseline = self.sync.manifests(repo)

            mirror_file = repo / "config/home/.config/example/settings.conf"
            self.assertEqual(mirror_file.read_text(encoding="utf-8"), "enabled=true\n")
            self.assertEqual(active, mirror)
            self.assertEqual(active, baseline)
            self.assertEqual(command("git", "status", "--porcelain", cwd=repo), "")
            self.assertTrue(
                command("git", "log", "-1", "--format=%s", cwd=repo).startswith("config-sync(")
            )

    def test_json_status_is_native_config_sync_contract(self) -> None:
        args = self.sync.parser().parse_args(
            self.sync.normalize_argv(["status", "--json", "--offline", "--scope", "nixos"])
        )
        self.assertTrue(args.json)
        self.assertEqual(args.command, "status")
        self.assertEqual(args.scope, "nixos")

    def test_yes_mode_commits_without_prompt(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            repo = Path(directory)
            command("git", "init", str(repo))
            configure_identity(repo)
            (repo / "flake.nix").write_text("one\n", encoding="utf-8")
            command("git", "add", "flake.nix", cwd=repo)
            command("git", "commit", "-m", "initial", cwd=repo)
            (repo / "flake.nix").write_text("two\n", encoding="utf-8")

            with mock.patch.object(
                builtins, "input", side_effect=AssertionError("input must not be called")
            ):
                changed = self.sync.commit_and_push(
                    repo,
                    scope="nixos",
                    message=None,
                    no_commit=False,
                    offline=True,
                    assume_yes=True,
                )

            self.assertTrue(changed)
            self.assertTrue(
                command("git", "log", "-1", "--format=%s", cwd=repo).startswith("config-sync(")
            )
            self.assertEqual(command("git", "status", "--porcelain", cwd=repo), "")


if __name__ == "__main__":
    unittest.main()
