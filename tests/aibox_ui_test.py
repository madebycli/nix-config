#!/usr/bin/env python3
"""Browser-launch lifecycle and real localhost readiness without a model/GPU."""
import contextlib
import http.server
import importlib.util
import json
import os
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("aibox", ROOT / "pkgs/aibox/aibox.py")
aibox = importlib.util.module_from_spec(spec)
spec.loader.exec_module(aibox)


def running(port="8766", host="127.0.0.1", mode="manager"):
    return {"State": {"Running": True}, "Config": {"Labels": {f"{aibox.LABEL}.mode": mode}},
            "NetworkSettings": {"Ports": {"8080/tcp": [{"HostIp": host, "HostPort": port}]}}}


class BrowserUI(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.cfg = {"modelDirectory": self.tmp.name}
        self.health = {"ok": True, "backend": {}, "engine": {}}

    def test_empty_library_opens_full_manager_without_mock_model(self):
        with patch.object(aibox, "owned_server", return_value=None), patch.object(aibox, "start_ui") as start, patch.object(aibox, "wait_for_ui", return_value=self.health), patch.object(aibox.subprocess, "run", return_value=Mock(returncode=0)) as browser:
            aibox.ui(self.cfg)
        start.assert_called_once_with(self.cfg, 8766)
        self.assertEqual(browser.call_args.args[0], ["xdg-open", "http://127.0.0.1:8766"])

    def test_existing_private_model_is_not_interrupted_or_published(self):
        data = running(mode="model")
        data["NetworkSettings"]["Ports"] = {}
        with patch.object(aibox, "owned_server", return_value=data), patch.object(aibox, "start_ui") as start:
            with self.assertRaisesRegex(ValueError, "aibox stop"):
                aibox.ui(self.cfg)
        start.assert_not_called()

    def test_existing_ui_is_reused_without_start_or_browser_in_headless_mode(self):
        with patch.object(aibox, "owned_server", return_value=running()), patch.object(aibox, "start_ui") as start, patch.object(aibox, "wait_for_ui", return_value=self.health), patch.object(aibox.subprocess, "run") as browser:
            aibox.ui(self.cfg, no_open=True)
        start.assert_not_called()
        browser.assert_not_called()

    def test_ui_rejects_wildcard_lan_and_other_ports(self):
        for host in ("0.0.0.0", "::", "192.168.1.5"):
            with self.subTest(host=host), self.assertRaises(ValueError):
                aibox.ui_binding(running(host=host))
        with patch.object(aibox, "owned_server", return_value=running(port="8767")):
            with self.assertRaisesRegex(ValueError, "8767"):
                aibox.ui(self.cfg, no_open=True)

    def test_invalid_port_has_no_side_effects(self):
        for port in (0, 80, 65536):
            with patch.object(aibox, "owned_server") as inspect:
                with self.assertRaises(ValueError):
                    aibox.ui(self.cfg, port=port)
                inspect.assert_not_called()

    def test_headless_open_failure_preserves_the_server_and_prints_url(self):
        with patch.object(aibox, "owned_server", return_value=running()), patch.object(aibox, "wait_for_ui", return_value=self.health), patch.object(aibox.subprocess, "run", side_effect=FileNotFoundError), patch("builtins.print") as output:
            aibox.ui(self.cfg)
        self.assertTrue(any("http://127.0.0.1:8766" in str(call) for call in output.call_args_list))

    def test_manager_has_separate_state_models_and_outbound_network(self):
        models = Path(self.tmp.name) / "models"
        models.mkdir()
        cfg = {"modelDirectory": str(models)}
        net = {"internal": False, "labels": {aibox.LABEL: "true"}}
        with patch.object(aibox, "manager_image", return_value="manager"), patch.object(aibox, "ensure_image"), patch.object(aibox, "ensure_network"), patch.object(aibox, "owned_server", return_value=None), patch.object(aibox, "gpu_args", return_value=["--device=/dev/kfd"]), patch.object(aibox, "exists", return_value=True), patch.object(aibox, "run", return_value=Mock(stdout=json.dumps([net]))) as run:
            aibox.start_ui(cfg, 8766)
        args = run.call_args.args
        self.assertEqual(args[args.index("--publish") + 1], "127.0.0.1:8766:8080")
        self.assertIn(aibox.NETWORK, args)
        self.assertIn("nx-ai-downloads", args)
        mounts = [args[i + 1] for i, x in enumerate(args) if x == "--mount"]
        self.assertEqual(len(mounts), 2)
        self.assertTrue(any("target=/models,bind-nonrecursive" in x for x in mounts))
        self.assertTrue(any("target=/state,bind-nonrecursive" in x for x in mounts))
        self.assertFalse(any("podman.sock" in x or "target=/work" in x for x in mounts))
        self.assertIn("--read-only", args)
        self.assertIn("--cap-drop=ALL", args)
        self.assertIn("--device=/dev/kfd", args)
        self.assertEqual(args[-1], "manager")

    def test_workspace_cannot_expose_manager_state(self):
        models = Path(self.tmp.name) / "models"
        models.mkdir()
        state = Path(self.tmp.name) / "manager"
        state.mkdir()
        with self.assertRaisesRegex(ValueError, "manager state"):
            aibox.agent_args({"modelDirectory": str(models)}, state, ["true"])

    def test_prepare_ui_reuses_engine_without_compiling_or_model_acquisition(self):
        with patch.dict(os.environ, {"AIBOX_SUPPORT": "/support"}), patch.object(aibox, "image_name", return_value="engine"), patch.object(aibox, "manager_image", return_value="manager"), patch.object(aibox, "ensure_image") as ensure, patch.object(aibox, "run") as run:
            aibox.prepare_ui({"gpuArch": "gfx1030"})
        ensure.assert_called_once_with("engine")
        args = run.call_args.args
        self.assertIn("ENGINE_IMAGE=engine", args)
        self.assertIn("/support/ManagerContainerfile", args)
        self.assertNotIn("prepare", args)

    @contextlib.contextmanager
    def server(self, payload, redirect=False):
        class Handler(http.server.BaseHTTPRequestHandler):
            unexpected = False

            def do_GET(self):
                if self.path != "/api/health":
                    self.__class__.unexpected = True
                body = json.dumps(payload).encode()
                self.send_response(302 if redirect else 200)
                if redirect:
                    self.send_header("Location", "/unexpected")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, *_):
                pass

        httpd = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        worker = threading.Thread(target=httpd.serve_forever, daemon=True)
        worker.start()
        try:
            yield f"http://127.0.0.1:{httpd.server_port}", Handler
        finally:
            httpd.shutdown()
            httpd.server_close()
            worker.join(timeout=2)

    def test_real_readiness_request_ignores_host_proxy(self):
        with self.server(self.health) as (url, _), patch.dict(os.environ, {"http_proxy": "http://127.0.0.1:1", "HTTP_PROXY": "http://127.0.0.1:1", "NO_PROXY": "", "no_proxy": ""}):
            self.assertEqual(aibox.wait_for_ui(url), self.health)

    def test_another_http_service_is_not_opened_as_strata(self):
        with self.server({"status": "ok", "service": "strata"}) as (url, _):
            with self.assertRaisesRegex(ValueError, "did not answer as Strata"):
                aibox.wait_for_ui(url)

    def test_redirect_is_not_followed(self):
        with self.server(self.health, redirect=True) as (url, handler):
            with self.assertRaisesRegex(ValueError, "not ready"):
                aibox.wait_for_ui(url, timeout=0.05)
            self.assertFalse(handler.unexpected)


if __name__ == "__main__":
    unittest.main()
