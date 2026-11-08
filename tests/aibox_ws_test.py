#!/usr/bin/env python3
"""Named workspaces: isolation of project, tools, chat history; safe creation and deletion."""
import importlib.util
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("aibox", ROOT / "pkgs/aibox/aibox.py")
aibox = importlib.util.module_from_spec(spec)
spec.loader.exec_module(aibox)


class Workspaces(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.home = Path(tmp.name).resolve() / "h"
        (self.home / ".local/share/nx-ai/models").mkdir(parents=True)
        self.cfg = {"modelDirectory": str(self.home / ".local/share/nx-ai/models")}
        support = Path(tmp.name) / "support"
        support.mkdir()
        for name in ("DevContainerfile", "shot.sh", "SKILLS.md", "longctx_probe.py"):
            (support / name).write_text(name)
        env = patch.dict(os.environ, {"HOME": str(self.home), "AIBOX_SUPPORT": str(support),
                                      "AIBOX_AGENT_IMAGE": "localhost/test:fixed"})
        env.start()
        self.addCleanup(env.stop)

    def mounts(self, args):
        return [args[i + 1] for i, a in enumerate(args) if a == "--mount"]

    def test_new_creates_isolated_workspaces_with_own_project_tools_and_history(self):
        a, created = aibox.ws_new(self.cfg, "chat-app", template="android")
        b, _ = aibox.ws_new(self.cfg, "nixos", template="nix")
        self.assertTrue(created)
        self.assertEqual({m["name"] for m in aibox.ws_list(self.cfg)}, {"chat-app", "nixos"})
        args_a = aibox.ws_agent_args(self.cfg, "chat-app", ["true"])
        args_b = aibox.ws_agent_args(self.cfg, "nixos", ["true"])
        ma, mb = self.mounts(args_a), self.mounts(args_b)
        self.assertEqual(len(ma), 3)
        self.assertTrue(ma[0].startswith(f"type=bind,src={a['project']},target=/work"))
        self.assertIn("target=/tools", ma[1])
        self.assertIn("target=/state", ma[2])
        self.assertTrue(set(ma[1:]).isdisjoint(mb[1:]))  # separate tools and chat history
        self.assertIn("--env=AIBOX_STATE_HOME=/state", args_a)
        self.assertTrue(ma[2].split(",")[1].endswith("/home"))  # workspace.json is never mounted
        self.assertIn("Android", (Path(a["project"]) / "AGENTS.md").read_text())

    def test_tools_group_can_be_shared_deliberately(self):
        aibox.ws_new(self.cfg, "one", tools_group="android")
        aibox.ws_new(self.cfg, "two", tools_group="android")
        m1 = self.mounts(aibox.ws_agent_args(self.cfg, "one", ["true"]))[1]
        m2 = self.mounts(aibox.ws_agent_args(self.cfg, "two", ["true"]))[1]
        self.assertEqual(m1, m2)

    def test_names_templates_and_overlaps_are_validated(self):
        for bad in ("", "Up", "a/b", "../x", "x" * 41, "-x"):
            with self.assertRaises(ValueError, msg=bad):
                aibox.ws_new(self.cfg, bad)
        with self.assertRaises(ValueError):
            aibox.ws_new(self.cfg, "x", template="nope")
        aibox.ws_new(self.cfg, "dup")
        with self.assertRaises(ValueError):
            aibox.ws_new(self.cfg, "dup")
        with self.assertRaises(ValueError):
            aibox.ws_new(self.cfg, "inside", path=str(aibox.ws_root(self.cfg) / "inside"))

    def test_remove_keeps_the_project_by_default_and_removes_unshared_tools(self):
        meta, _ = aibox.ws_new(self.cfg, "gone")
        aibox.ws_agent_args(self.cfg, "gone", ["true"])  # creates the tools folder
        (Path(meta["project"]) / "keep.txt").write_text("x")
        aibox.ws_remove(self.cfg, "gone")
        self.assertTrue((Path(meta["project"]) / "keep.txt").exists())
        self.assertEqual(aibox.ws_list(self.cfg), [])
        self.assertFalse((aibox.ws_root(self.cfg) / "_tools" / "gone").exists())

    def test_shared_tools_survive_removing_one_workspace_and_project_removal_is_explicit(self):
        aibox.ws_new(self.cfg, "one", tools_group="g")
        meta, _ = aibox.ws_new(self.cfg, "two", tools_group="g")
        aibox.ws_agent_args(self.cfg, "one", ["true"])
        aibox.ws_remove(self.cfg, "one")
        self.assertTrue((aibox.ws_root(self.cfg) / "_tools" / "g").exists())
        aibox.ws_remove(self.cfg, "two", with_project=True)
        self.assertFalse(Path(meta["project"]).exists())

    def test_tampered_metadata_cannot_escape(self):
        meta, _ = aibox.ws_new(self.cfg, "t")
        path = aibox.ws_dir(self.cfg, "t") / "workspace.json"
        path.write_text(json.dumps({**meta, "toolsGroup": "../../etc"}))
        with self.assertRaises(ValueError):
            aibox.ws_agent_args(self.cfg, "t", ["true"])
        path.write_text(json.dumps({**meta, "name": "other"}))
        with self.assertRaises(ValueError):
            aibox.ws_load(self.cfg, "t")
        path.write_text(json.dumps({**meta, "project": str(self.home)}))
        with self.assertRaises(ValueError):
            aibox.ws_agent_args(self.cfg, "t", ["true"])


if __name__ == "__main__":
    unittest.main()
