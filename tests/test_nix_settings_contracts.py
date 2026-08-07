from __future__ import annotations

import argparse
import importlib.util
import sys
import tempfile
import unittest
from dataclasses import dataclass
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


class FakeSyncBackend:
    MIRROR_PREFIX = Path("config/home")

    class SyncError(RuntimeError):
        pass

    def __init__(self, root: Path) -> None:
        self.root = root

    def find_repo(self, _explicit: str | None) -> Path:
        return self.root

    @staticmethod
    def ensure_remote(_repo: Path) -> None:
        return None

    @staticmethod
    def fetch(_repo: Path, _offline: bool) -> None:
        return None

    @staticmethod
    def relation(_repo: Path) -> tuple[int, int, str]:
        return 1, 0, "origin/main"

    @staticmethod
    def git(_repo: Path, *args: str) -> str:
        if args == ("branch", "--show-current"):
            return "main"
        if args == ("diff", "--cached", "--name-only"):
            return "flake.nix\nmodules/example.nix"
        raise AssertionError(args)

    @staticmethod
    def load_state(_repo: Path) -> dict[str, object]:
        return {"last_sync": None, "last_synced_commit": None}

    @staticmethod
    def worktree_lines(_repo: Path) -> list[str]:
        return [" M flake.nix"]

    def state_dir(self, _repo: Path) -> Path:
        return self.root / ".state"

    @staticmethod
    def profile_from_state(_repo: Path, _explicit: str | None) -> str:
        return "nyx"


@dataclass(frozen=True)
class FakeAuthStatus:
    gh_installed: bool = True
    authenticated: bool = True
    login: str | None = "madebycli"
    permission: str | None = "ADMIN"
    can_push: bool = True
    remote_url: str | None = "https://github.com/madebycli/nix-config.git"
    remote_ok: bool = True
    git_name: str | None = "madebycli"
    git_email: str | None = "example@users.noreply.github.com"
    credential_helper_ready: bool = True
    error: str | None = None


class FakeAuthBackend:
    REPOSITORY = "madebycli/nix-config"

    class AuthError(RuntimeError):
        pass

    @staticmethod
    def status(_repo: Path) -> FakeAuthStatus:
        return FakeAuthStatus()


class FakeSignedOutAuthBackend(FakeAuthBackend):
    @staticmethod
    def status(_repo: Path) -> FakeAuthStatus:
        return FakeAuthStatus(
            authenticated=False,
            login=None,
            permission=None,
            can_push=False,
            credential_helper_ready=False,
            error="Not signed in to GitHub CLI",
        )


class ContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.sync_json = load_script("nix_config_sync_json_test", "config-sync-json.py")
        cls.helper = load_script("nix_settings_helper_test", "nix-settings-helper.py")

    def test_sync_status_serializes_staged_paths_and_github_state(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            args = argparse.Namespace(repo=None, offline=True, scope="nixos")
            payload = self.sync_json.status_payload(
                FakeSyncBackend(root), FakeAuthBackend(), args
            )
        self.assertEqual(payload["stagedChanges"], ["flake.nix", "modules/example.nix"])
        self.assertTrue(payload["dirty"])
        self.assertEqual(payload["github"]["login"], "madebycli")
        self.assertTrue(payload["github"]["canPush"])
        self.assertNotIn("token", payload["github"])

    def test_signed_out_github_state_is_not_a_global_sync_error(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            args = argparse.Namespace(repo=None, offline=True, scope="nixos")
            payload = self.sync_json.status_payload(
                FakeSyncBackend(root), FakeSignedOutAuthBackend(), args
            )
        self.assertEqual(payload["errors"], [])
        self.assertFalse(payload["github"]["authenticated"])
        self.assertEqual(payload["github"]["error"], "Not signed in to GitHub CLI")

    def test_helper_mode_mapping(self) -> None:
        self.assertEqual(
            self.helper.MODE_INPUTS["desktop"],
            ("home-manager", "mango", "noctalia", "noctalia-greeter"),
        )
        self.assertEqual(self.helper.MODE_INPUTS["profiles"], ())

    def test_helper_rejects_arbitrary_command(self) -> None:
        with (
            mock.patch.object(self.helper.os, "geteuid", return_value=0),
            mock.patch.object(self.helper, "event"),
        ):
            with self.assertRaises(self.helper.HelperError):
                self.helper.dispatch(["sh", "-c", "id"])


if __name__ == "__main__":
    unittest.main()
