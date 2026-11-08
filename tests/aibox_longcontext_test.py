#!/usr/bin/env python3
"""Optional KVMem long-context mode: explicit settings, fail-closed memory checks, unchanged 16K path."""
import importlib.util
import json
import os
from pathlib import Path
import re
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("aibox", ROOT / "pkgs/aibox/aibox.py")
aibox = importlib.util.module_from_spec(spec)
spec.loader.exec_module(aibox)


class LongContext(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.models = Path(tmp.name) / "models"
        (self.models / "qwen27-iq4xs").mkdir(parents=True)
        self.cfg = {"modelDirectory": str(self.models), "gpuArch": "gfx1030", "hipBaseImage": "test:fixed",
                    "buildJobs": 2, "renderDevice": "/dev/dri/renderD128", "longContext": {}}
        env = patch.dict(os.environ, {"AIBOX_SUPPORT": str(ROOT / "pkgs/aibox")})
        env.start()
        self.addCleanup(env.stop)

    def args(self, preset="lc256", **cfg):
        settings = aibox.longcontext_settings({**self.cfg, **cfg}, preset, allow_experimental=True)
        return settings, aibox.kvmem_server_args(self.cfg, "qwen27-iq4xs", settings)

    def test_presets_cover_64k_128k_256k_and_500k_experimental(self):
        presets = aibox.longcontext_presets()
        self.assertEqual({k: v["workspace"] for k, v in presets.items()},
                         {"lc64": 65536, "lc128": 131072, "lc256": 262144, "lc512": 524288, "lc256-iq3": 262144})
        self.assertEqual([k for k, v in presets.items() if v["experimental"]], ["lc512"])
        with self.assertRaises(ValueError):
            aibox.longcontext_settings(self.cfg, "lc512")

    def test_server_args_keep_q8_mtp2_explicit_memory_and_no_fit_or_offload_flags(self):
        settings, args = self.args()
        for flag, value in (("--ctx-size", "262144"), ("--spec-type", "draft-mtp"),
                            ("--spec-draft-n-max", "2"), ("--spec-kv-dtype", "q8_0"), ("--kvmem-mtp-state", "replay"),
                            ("--kvmem-budget", "12288"), ("--kvmem-gen-reserve", "4096"), ("--kvmem-host-mib", "12288"),
                            ("--gpu-layers", "999"), ("--load-mode", "none"), ("--device", "ROCm0")):
            self.assertEqual(args[args.index(flag) + 1], value, flag)
        self.assertEqual(args[args.index("--cache-type-k") + 1], "q8_0")
        self.assertEqual(args[args.index("--cache-type-v") + 1], "q8_0")
        self.assertIn("--no-mmproj-offload", args)
        self.assertNotIn("--fit", args)

    def test_q5_kv_is_explicit_opt_in_and_shrinks_estimate(self):
        _, q5 = self.args(longContext={"kvDtype": "q5_0"})
        self.assertEqual(q5[q5.index("--cache-type-k") + 1], "q5_0")
        self.assertEqual(q5[q5.index("--spec-kv-dtype") + 1], "q5_0")
        with self.assertRaises(ValueError):
            aibox.longcontext_settings({**self.cfg, "longContext": {"kvDtype": "q2_0"}}, "lc64")

    def test_k8v4_and_q4_types_and_iq3_preset_fail_closed_without_pins(self):
        _, mixed = self.args(longContext={"kvDtype": "k8v4"})
        self.assertEqual((mixed[mixed.index("--cache-type-k") + 1], mixed[mixed.index("--cache-type-v") + 1],
                          mixed[mixed.index("--spec-kv-dtype") + 1]), ("q8_0", "q4_0", "q8_0"))
        _, four = self.args(longContext={"kvDtype": "q4_0"})
        self.assertEqual(four[four.index("--cache-type-k") + 1], "q4_0")
        self.assertEqual(four[four.index("--spec-kv-dtype") + 1], "q8_0")
        preset = aibox.longcontext_settings(self.cfg, "lc256-iq3")
        self.assertEqual((preset["kvDtype"], preset["gpuBudget"], preset["workspace"]), ("k8v4", 32768, 262144))
        self.assertEqual(aibox.longcontext_profile(self.cfg, "lc256-iq3"), "qwen27-iq3")
        with patch.object(aibox, "profiles", return_value={}), \
             self.assertRaisesRegex(ValueError, "pinned files are not in profiles.json"):
            aibox.longcontext_profile(self.cfg, "lc256-iq3")
        with self.assertRaises(ValueError):
            aibox.longcontext_profile(self.cfg, "lc256-iq3", "qwen27-iq4xs")

    def test_prism_path_kv_type_is_opt_in(self):
        a = aibox.llama_server_args({**self.cfg, "kvCacheType": "k8v4"}, "qwen27-iq4xs")
        self.assertEqual((a[a.index("--cache-type-k") + 1], a[a.index("--cache-type-v") + 1]), ("q8_0", "q4_0"))
        with self.assertRaises(ValueError):
            aibox.llama_server_args({**self.cfg, "kvCacheType": "q2_0"}, "qwen27-iq4xs")

    def test_image_token_bounds_are_explicit_and_default_unchanged(self):
        _, base = self.args()
        self.assertEqual(base[base.index("--image-max-tokens") + 1], "512")
        self.assertNotIn("--image-min-tokens", base)
        _, big = self.args(longContext={"imageMinTokens": 1024, "imageMaxTokens": 2048})
        self.assertEqual((big[big.index("--image-min-tokens") + 1], big[big.index("--image-max-tokens") + 1]), ("1024", "2048"))

    def test_vision_can_be_omitted_only_explicitly(self):
        settings, _ = self.args()
        text = aibox.kvmem_server_args(self.cfg, "qwen27-iq4xs", settings, vision=False)
        self.assertNotIn("--mmproj", text)

    def test_overrides_validated_never_adjusted(self):
        for bad in ({"gpuBudget": 12289}, {"genReserve": 100}, {"hostKvMiB": 30000, "containerRamMiB": 20000},
                    {"gpuBudget": 262144, "genReserve": 4096}):
            with self.assertRaises(ValueError, msg=bad):
                aibox.longcontext_settings({**self.cfg, "longContext": bad}, "lc256")
        ok = aibox.longcontext_settings({**self.cfg, "longContext": {"gpuBudget": 8192}}, "lc256")
        self.assertEqual(ok["gpuBudget"], 8192)

    def test_plan_refuses_insufficient_vram_and_ram_without_changing_settings(self):
        settings = aibox.longcontext_settings(self.cfg, "lc256")
        (self.models / "qwen27-iq4xs" / "x").write_text("")
        with patch.object(aibox, "vram_mib", return_value=(16368, 16000)), \
             patch.object(aibox, "meminfo_mib", return_value={"MemAvailable": 4096, "SwapTotal": 0}):
            plan, problems = aibox.longcontext_plan(self.cfg, "qwen27-iq4xs", settings)
        self.assertEqual(len(problems), 2)
        self.assertTrue(any("VRAM" in p for p in problems) and any("RAM" in p for p in problems))
        self.assertEqual(settings["gpuBudget"], 12288)
        self.assertGreater(plan["estimate_mib"]["weights"], 14000)

    def test_plan_passes_with_free_memory_and_warns_when_vram_unreadable(self):
        settings = aibox.longcontext_settings(self.cfg, "lc128")
        with patch.object(aibox, "vram_mib", return_value=(16368, 20)), \
             patch.object(aibox, "meminfo_mib", return_value={"MemAvailable": 28000, "SwapTotal": 0}):
            self.assertEqual(aibox.longcontext_plan(self.cfg, "qwen27-iq4xs", settings)[1], [])
        with patch.object(aibox, "vram_mib", return_value=None), \
             patch.object(aibox, "meminfo_mib", return_value={"MemAvailable": 28000}):
            plan, problems = aibox.longcontext_plan(self.cfg, "qwen27-iq4xs", settings)
        self.assertEqual(problems, [])
        self.assertIn("unverified", plan["warning"])

    def test_bonsai_is_rejected_for_kvmem_and_16k_args_unchanged(self):
        with self.assertRaises(ValueError):
            aibox.start_llama(self.cfg, "bonsai27-pq2", long_context="lc64")
        args = aibox.llama_server_args(self.cfg, "qwen27-iq4xs")
        self.assertEqual(args[args.index("--ctx-size") + 1], "16384")
        self.assertIn("draft-mtp", args)

    def test_kvmem_image_is_independent_of_prism_image(self):
        before = aibox.llama_image(self.cfg)
        self.assertNotEqual(aibox.kvmem_image(self.cfg).split(":")[0], before.split(":")[0])
        self.assertEqual(before, aibox.llama_image(self.cfg))

    def test_containerfile_pins_full_revisions_and_probes_required_flags(self):
        text = (ROOT / "pkgs/aibox/KvmemContainerfile").read_text()
        self.assertRegex(text, r"KVMEM_REV=[0-9a-f]{40}")
        self.assertRegex(text, r"LLAMA_BASE=[0-9a-f]{40}")
        self.assertIn("prepare-backends.py --backend llamacpp --check", text)
        self.assertNotIn("RyensX", text)
        for flag in ("--kvmem-host-mib", "--spec-kv-dtype", "--no-mmproj-offload"):
            self.assertIn(flag, text)


if __name__ == "__main__":
    unittest.main()
