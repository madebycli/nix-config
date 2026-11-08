#!/usr/bin/env python3
"""Pinned profile selection, artifact integrity and MTP fail-closed policy."""
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("aibox", ROOT / "pkgs/aibox/aibox.py")
aibox = importlib.util.module_from_spec(spec)
spec.loader.exec_module(aibox)
guard_spec = importlib.util.spec_from_file_location("require_mtp", ROOT / "pkgs/aibox/require-mtp.py")
guard = importlib.util.module_from_spec(guard_spec)
guard_spec.loader.exec_module(guard)


class Profiles(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        self.models = self.root / "models"
        self.models.mkdir()
        self.cfg = {"modelDirectory": str(self.models), "gpuArch": "gfx1030",
                    "hipBaseImage": "test:fixed", "buildJobs": 2, "renderDevice": "/dev/dri/renderD128"}
        env = patch.dict(os.environ, {"AIBOX_SUPPORT": str(ROOT / "pkgs/aibox")})
        env.start()
        self.addCleanup(env.stop)

    def fixture(self, name="bonsai27-pq2"):
        directory = self.models / name
        directory.mkdir(exist_ok=True)
        content = b"GGUF fixture only"
        files = []
        for role in ("model", "projector"):
            item = {"role": role, "repo": "owner/repo", "revision": "a" * 40,
                    "name": role + ".gguf", "size": len(content),
                    "sha256": hashlib.sha256(content).hexdigest()}
            files.append(item)
            (directory / item["name"]).write_bytes(content)
        return {name: {"name": "fixture", "provenance": "fixture source", "files": files}}

    def test_both_profiles_force_q8_target_and_draft_cache_mtp2_and_explicit_context(self):
        for name in aibox.profiles():
            (self.models / name).mkdir()
            args = aibox.llama_server_args(self.cfg, name)
            for flag, value in (("--cache-type-k", "q8_0"), ("--cache-type-v", "q8_0"),
                                ("--spec-draft-type-k", "q8_0"), ("--spec-draft-type-v", "q8_0"),
                                ("--spec-type", "draft-mtp"), ("--spec-draft-n-max", "2"),
                                ("--ctx-size", "16384"), ("--device", "ROCm0"),
                                ("--fit", "off"), ("--load-mode", "none"), ("--parallel", "1")):
                self.assertEqual(args[args.index(flag) + 1], value)
            self.assertIn("--mmproj", args)
            self.assertNotIn("--mmproj", aibox.llama_server_args(self.cfg, name, vision=False))

    def test_context_override_is_explicit_and_invalid_values_rejected(self):
        self.fixture()
        cfg = {**self.cfg, "contextSize": 32768}
        args = aibox.llama_server_args(cfg, "bonsai27-pq2")
        self.assertEqual(args[args.index("--ctx-size") + 1], "32768")
        for value in (0, True, "16384", 262145):
            with self.assertRaises(ValueError):
                aibox.llama_server_args({**cfg, "contextSize": value}, "bonsai27-pq2")

    def test_manifest_has_immutable_revisions_hashes_and_distinct_projectors(self):
        entries = aibox.profiles()
        self.assertEqual(set(entries), {"qwen27-iq4xs", "qwen27-iq3", "bonsai27-pq2"})
        for entry in entries.values():
            self.assertEqual({x["role"] for x in entry["files"]}, {"model", "projector"})
            for item in entry["files"]:
                self.assertRegex(item["revision"], r"^[0-9a-f]{40}$")
                self.assertRegex(item["sha256"], r"^[0-9a-f]{64}$")
                self.assertGreater(item["size"], 1)
        self.assertIn("community", entries["bonsai27-pq2"]["provenance"])

    def test_unknown_profile_cannot_become_a_path_or_download(self):
        for value in ("../other", "/etc", "anything"):
            with self.assertRaises(ValueError):
                aibox.profile(self.cfg, value)

    def test_corrupt_model_refused_before_network_gpu_or_container_changes(self):
        catalog = self.fixture()
        (self.models / "bonsai27-pq2/model.gguf").write_bytes(b"X" * len(b"GGUF fixture only"))
        with patch.object(aibox, "profiles", return_value=catalog), patch.object(aibox, "owned_server", return_value=None), patch.object(aibox, "exists", return_value=True), patch.object(aibox, "run") as run, patch.object(aibox, "gpu_args") as gpu:
            with self.assertRaisesRegex(ValueError, "SHA256 mismatch"):
                aibox.start_llama(self.cfg, "bonsai27-pq2")
        run.assert_not_called()
        gpu.assert_not_called()

    def test_fetch_is_explicit_pinned_and_atomic(self):
        catalog = self.fixture()
        directory = self.models / "bonsai27-pq2"
        for p in directory.iterdir():
            p.unlink()
        def download(args, **kwargs):
            self.assertIn("/resolve/" + "a" * 40 + "/", args[-1])
            self.assertEqual(args[args.index("--proto-redir") + 1], "=https")
            target = Path(args[args.index("--output") + 1])
            self.assertEqual(target.suffix, ".part")
            target.write_bytes(b"GGUF fixture only")
        with patch.object(aibox, "profiles", return_value=catalog), patch.object(aibox.subprocess, "run", side_effect=download) as download_call:
            aibox.fetch_profile(self.cfg, "bonsai27-pq2")
            self.assertEqual(download_call.call_count, 2)
            aibox.fetch_profile(self.cfg, "bonsai27-pq2")
            self.assertEqual(download_call.call_count, 2)
        self.assertEqual(len(list(directory.iterdir())), 2)

    def test_symlink_artifacts_and_profile_directories_are_refused(self):
        catalog = self.fixture()
        dest = self.models / "bonsai27-pq2/model.gguf"
        dest.unlink()
        dest.symlink_to(self.root / "outside")
        with patch.object(aibox, "profiles", return_value=catalog), patch.object(aibox.subprocess, "run") as download:
            with self.assertRaises(ValueError):
                aibox.fetch_profile(self.cfg, "bonsai27-pq2")
        download.assert_not_called()
        (self.models / "qwen27-iq4xs").symlink_to(self.root, target_is_directory=True)
        with self.assertRaises(ValueError):
            aibox.profile_directory(self.cfg, "qwen27-iq4xs")

    def test_start_mounts_only_verified_profile_readonly_and_uses_internal_network(self):
        catalog = self.fixture()
        with patch.object(aibox, "profiles", return_value=catalog), patch.object(aibox, "exists", return_value=True), patch.object(aibox, "gpu_args", return_value=["--device=/dev/kfd"]), patch.object(aibox, "ensure_network"), patch.object(aibox, "owned_server", return_value=None), patch.object(aibox, "wait_for_llama"), patch.object(aibox, "run") as run:
            aibox.start_llama(self.cfg, "bonsai27-pq2")
        args = run.call_args.args
        self.assertEqual(args[args.index("--network") + 1], aibox.NETWORK)
        self.assertNotIn("--publish", args)
        self.assertIn("--read-only", args)
        mounts = [args[i+1] for i,x in enumerate(args) if x == "--mount"]
        self.assertEqual(mounts, [f"type=bind,src={self.models}/bonsai27-pq2,target=/models,ro,bind-nonrecursive"])
        self.assertEqual(args[args.index("--spec-draft-n-max")+1], "2")

    def test_ui_binding_is_loopback_and_invalid_port_has_no_side_effect(self):
        catalog = self.fixture()
        with patch.object(aibox, "profiles", return_value=catalog), patch.object(aibox, "exists", return_value=True), patch.object(aibox, "gpu_args", return_value=[]), patch.object(aibox, "ensure_network"), patch.object(aibox, "owned_server", return_value=None), patch.object(aibox, "wait_for_llama"), patch.object(aibox, "run") as run:
            aibox.start_llama(self.cfg, "bonsai27-pq2", port=8766)
            self.assertIn("127.0.0.1:8766:8080", run.call_args.args)
            run.reset_mock()
            with self.assertRaises(ValueError):
                aibox.start_llama(self.cfg, "bonsai27-pq2", port=80)
            run.assert_not_called()

    def test_ui_reopens_matching_running_profile_without_restarting(self):
        self.fixture()
        data = {"State": {"Running": True},
                "Config": {"Labels": {f"{aibox.LABEL}.mode": "llama", f"{aibox.LABEL}.profile": "bonsai27-pq2"},
                           "Cmd": aibox.llama_server_args(self.cfg, "bonsai27-pq2")},
                "NetworkSettings": {"Ports": {"8080/tcp": [{"HostIp": "127.0.0.1", "HostPort": "8766"}]}}}
        with patch.object(aibox, "owned_server", return_value=data), patch.object(aibox, "wait_for_llama"), patch.object(aibox, "run") as run:
            aibox.start_llama(self.cfg, "bonsai27-pq2", port=8766)
            run.assert_not_called()
            with self.assertRaisesRegex(ValueError, "changing profiles"):
                aibox.start_llama(self.cfg, "bonsai27-pq2", port=8766, vision=False)

    def test_health_without_mtp_confirmation_stops_server(self):
        data = {"State": {"Running": True}}
        with patch.object(aibox, "owned_server", return_value=data), patch.object(aibox, "run", return_value=Mock(returncode=0, stdout="healthy", stderr="")) as run:
            with self.assertRaisesRegex(ValueError, "MTP activation"):
                aibox.wait_for_llama()
        self.assertEqual(run.call_args.args[0], "stop")

    def test_image_does_not_rebuild_for_context_or_profile_selection(self):
        self.assertEqual(aibox.llama_image(self.cfg), aibox.llama_image({**self.cfg, "contextSize": 32768, "defaultProfile": "bonsai27-pq2"}))
        self.assertNotEqual(aibox.llama_image(self.cfg), aibox.llama_image({**self.cfg, "gpuArch": "gfx1100"}))

    def test_source_guard_refuses_drift_instead_of_patching_random_location(self):
        source = self.root / "source/tools/server"
        source.mkdir(parents=True)
        path = source / "server-context.cpp"
        path.write_text("unrelated source")
        with self.assertRaisesRegex(ValueError, "anchor changed"):
            guard.patch(self.root / "source")
        anchor = "        for (int i = 0; i < params_base.n_parallel; i++) {\n            server_slot & slot = slots[i];"
        path.write_text(anchor)
        guard.patch(self.root / "source")
        self.assertIn("requires active draft-mtp; refusing fallback", path.read_text())
        with self.assertRaises(ValueError):
            # The anchor remains once: explicitly reject duplicate guard application.
            guard.patch(self.root / "source")


if __name__ == "__main__":
    unittest.main()
