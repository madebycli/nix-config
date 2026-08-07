from __future__ import annotations

import json
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WRAPPER = ROOT / "scripts" / "config-sync-wrapper.sh"


class ConfigSyncJsonWrapperTests(unittest.TestCase):
    def test_status_json_discards_human_stdout_before_payload(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            auth = root / "auth.py"
            backend = root / "backend.py"
            auth.write_text("# unused for status\n", encoding="utf-8")
            backend.write_text(
                "import json\n"
                "print('\\n==> GitHub-Stand wird geprüft')\n"
                "print('fetch progress that must not reach JSON clients')\n"
                "print(json.dumps({'schemaVersion': 1, 'repositoryPath': '/tmp/nyx'}))\n",
                encoding="utf-8",
            )

            completed = subprocess.run(
                [
                    "bash",
                    str(WRAPPER),
                    str(auth),
                    str(backend),
                    "status",
                    "--json",
                    "--scope",
                    "all",
                ],
                check=True,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )

        payload = json.loads(completed.stdout)
        self.assertEqual(payload["schemaVersion"], 1)
        self.assertEqual(payload["repositoryPath"], "/tmp/nyx")
        self.assertNotIn("GitHub-Stand", completed.stdout)
        self.assertNotIn("fetch progress", completed.stdout)


if __name__ == "__main__":
    unittest.main()
