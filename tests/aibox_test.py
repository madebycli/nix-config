#!/usr/bin/env python3
"""Safety boundaries and fail-closed behavior without models, Nix or a GPU."""
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch, Mock

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("aibox", ROOT / "pkgs/aibox/aibox.py")
aibox = importlib.util.module_from_spec(spec)
spec.loader.exec_module(aibox)
entry_spec = importlib.util.spec_from_file_location("entrypoint", ROOT / "pkgs/aibox/entrypoint.py")
entrypoint = importlib.util.module_from_spec(entry_spec)
entry_spec.loader.exec_module(entrypoint)


class ContainerPolicy(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.project = self.root / "project with spaces"
        self.project.mkdir()
        self.models = self.root / "models"
        self.models.mkdir()
        self.cfg = {"modelDirectory": str(self.models)}
        env = patch.dict(os.environ, {"AIBOX_AGENT_IMAGE": "localhost/test:fixed"})
        env.start()
        self.addCleanup(env.stop)

    def test_only_workspace_is_bound_and_no_gpu_or_engine_socket(self):
        args = aibox.agent_args(self.cfg, self.project, ["python3", "-V"])
        mounts = [args[i + 1] for i, x in enumerate(args) if x == "--mount"]
        self.assertEqual(mounts, [f"type=bind,src={self.project},target=/work,bind-nonrecursive"])
        for forbidden in ("--privileged", "--network=host", "--pid=host", "--ipc=host", "--device", "--volume"):
            self.assertFalse(any(x == forbidden or x.startswith(forbidden + "=") for x in args))
        self.assertIn("--read-only", args)
        self.assertIn("--cap-drop=ALL", args)
        self.assertIn("--security-opt=no-new-privileges", args)
        self.assertIn("--http-proxy=false", args)
        self.assertEqual(args[args.index("--network") + 1], aibox.NETWORK)
        self.assertNotIn("--publish", args)

    def test_argument_text_is_not_host_shell_code(self):
        command = ["bash", "-c", "printf '%s' '$HOME; touch /host-sentinel'"]
        args = aibox.agent_args(self.cfg, self.project, command)
        self.assertEqual(args[-3:], command)
        self.assertNotIn("--env-host", args)

    def test_private_home_bootstrap_is_writable_and_does_not_share_state(self):
        # Execute the real bootstrap without namespaces; only the image's skill
        # file is replaced by a fixture. All generated homes stay inside the test.
        skill = self.root / "SKILLS.md"
        skill.write_text("fixture workflow")
        args = aibox.agent_args(self.cfg, self.project, ["true"])
        bootstrap = args[args.index("-c") + 1].replace("/share/aibox/SKILLS.md", str(skill))
        probe = '''import json, os, stat
from pathlib import Path
p = Path.home()
(p / "writable").write_text("ok")
print(json.dumps({"home": str(p), "mode": stat.S_IMODE(p.stat().st_mode),
"uid": p.stat().st_uid, "skills": (p / ".codex/AGENTS.md").read_text(),
"config_mode": stat.S_IMODE((p / ".codex/config.toml").stat().st_mode)}))
'''
        homes = []
        for _ in range(2):
            result = subprocess.run(["bash", "-e", "-c", bootstrap, "aibox", sys.executable, "-c", probe],
                                    env={**os.environ, "TMPDIR": str(self.root)},
                                    capture_output=True, text=True, check=True)
            data = json.loads(result.stdout)
            self.assertEqual(data["mode"], 0o700)
            self.assertEqual(data["config_mode"], 0o600)
            self.assertEqual(data["uid"], os.getuid())
            self.assertEqual(data["skills"], "fixture workflow")
            self.assertTrue(Path(data["home"]).is_relative_to(self.root))
            homes.append(data["home"])
        self.assertNotEqual(*homes)
        self.assertFalse(any(x.startswith("--tmpfs=") and ("uid=" in x or "gid=" in x) for x in args))

    def test_home_root_and_system_directories_are_rejected(self):
        for path in (Path.home(), "/", "/etc", "/nix" if Path("/nix").exists() else "/proc", "/run"):
            with self.subTest(path=path), self.assertRaises(ValueError):
                aibox.safe_directory(path)

    def test_symlink_to_home_is_rejected(self):
        link = self.root / "outside"
        link.symlink_to(Path.home(), target_is_directory=True)
        with self.assertRaises(ValueError):
            aibox.safe_directory(link)

    def test_overlapping_model_and_work_directories_are_rejected(self):
        for path in (self.models, self.root):
            with self.subTest(path=path), self.assertRaises(ValueError):
                aibox.agent_args(self.cfg, path, ["true"])

    def test_mount_option_injection_is_rejected(self):
        for name in ("evil,ro", "evil:ro", "evil\npath"):
            path = self.root / name
            path.mkdir()
            with self.assertRaises(ValueError):
                aibox.safe_directory(path)

    def test_internal_network_is_checked_not_assumed(self):
        for data in ({"internal": False, "labels": {aibox.LABEL: "true"}},
                     {"internal": True, "labels": {}}):
            with patch.object(aibox, "exists", return_value=True), patch.object(aibox, "run", return_value=Mock(stdout=json.dumps([data]))):
                with self.assertRaises(ValueError):
                    aibox.ensure_network()

    def test_new_network_is_internal(self):
        data = {"internal": True, "labels": {aibox.LABEL: "true"}}
        with patch.object(aibox, "exists", return_value=False), patch.object(aibox, "run", return_value=Mock(stdout=json.dumps([data]))) as run:
            aibox.ensure_network()
        self.assertIn("--internal", run.call_args_list[0].args)

    def test_missing_model_config_stops_before_network_or_gpu(self):
        with patch.object(aibox, "image_name", return_value="test"), patch.object(aibox, "ensure_image"), patch.object(aibox, "run") as run:
            with self.assertRaisesRegex(ValueError, "No server.json"):
                aibox.start(self.cfg)
        run.assert_not_called()

    def test_smoke_has_no_models_devices_or_published_ports(self):
        with patch.object(aibox, "image_name", return_value="test"), patch.object(aibox, "ensure_image"), patch.object(aibox, "ensure_network"), patch.object(aibox, "owned_server", return_value=None), patch.object(aibox, "run") as run:
            aibox.start(self.cfg, smoke=True)
        args = run.call_args.args
        self.assertEqual(args[-1], "smoke")
        self.assertNotIn("--mount", args)
        self.assertFalse(any(x.startswith("--device") or x.startswith("--publish") for x in args))

    def test_another_app_container_cannot_be_stopped(self):
        with patch.object(aibox, "exists", return_value=True), patch.object(aibox, "run", return_value=Mock(stdout='[{"Config":{"Labels":{}}}]')):
            with self.assertRaises(ValueError):
                aibox.owned_server()

    def test_subprocess_uses_argv_not_shell(self):
        with patch.object(aibox.subprocess, "run") as run:
            aibox.run("exec", "x; touch /sentinel")
        args, kwargs = run.call_args
        self.assertEqual(args[0][-1], "x; touch /sentinel")
        self.assertNotIn("shell", kwargs)

    def test_root_is_refused_even_for_prepare(self):
        with patch.object(aibox.os, "getuid", return_value=0), patch.object(aibox, "load_config") as config, patch("sys.argv", ["aibox", "prepare"]):
            with self.assertRaisesRegex(ValueError, "without sudo"):
                aibox.main()
        config.assert_not_called()

    def test_preparation_does_not_run_upstream_acquisition(self):
        text = (ROOT / "pkgs/aibox/Containerfile").read_text()
        self.assertNotIn("setup.sh", text)
        self.assertNotIn("setup.py", text)
        self.assertNotIn("huggingface", text)
        self.assertIn("-DCMAKE_HIP_ARCHITECTURES=${GPU_ARCH}", text)
        self.assertIn("--target strata strata-device", text)

    def test_mock_api_does_not_open_a_model(self):
        with patch("sys.argv", ["entrypoint", "smoke"]), patch.object(entrypoint.os, "execv") as execute, patch.object(Path, "read_text") as read:
            entrypoint.main()
        read.assert_not_called()
        self.assertIn("mock", execute.call_args.args[1])

    def test_optional_server_tools_and_executables_are_rejected(self):
        for extra in ("exe", "cwd", "mcp_servers", "tools", "images", "env"):
            config = {"args": [], "tokenizer": "/models/tokenizer", extra: "untrusted"}
            with self.subTest(extra=extra), patch("sys.argv", ["entrypoint", "serve"]), patch.object(Path, "is_file", return_value=True), patch.object(Path, "read_text", return_value=json.dumps(config)), patch.object(entrypoint.os, "execv") as execute:
                with self.assertRaises(ValueError):
                    entrypoint.main()
                execute.assert_not_called()

    def test_tokenizer_must_be_within_model_mount(self):
        for tokenizer in ("/home/user/tokenizer", "relative", "/models/../etc"):
            config = {"args": [], "tokenizer": tokenizer}
            with self.subTest(tokenizer=tokenizer), patch("sys.argv", ["entrypoint", "serve"]), patch.object(Path, "is_file", return_value=True), patch.object(Path, "read_text", return_value=json.dumps(config)):
                with self.assertRaises(ValueError):
                    entrypoint.main()


if __name__ == "__main__":
    unittest.main()
