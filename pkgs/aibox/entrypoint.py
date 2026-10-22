"""A model-free engine image. Model configuration is supplied read-only later."""
import json
import os
from pathlib import Path
import sys

ROOT = Path("/opt/strata")


def main():
    mode = sys.argv[1] if len(sys.argv) == 2 else ""
    if mode == "devices":
        os.execv(str(ROOT / "build-hip/strata-device"), ["strata-device"])
    if mode == "smoke":
        args = ["--engine", "mock"]
    elif mode == "serve":
        source = Path("/models/server.json")
        if not source.is_file():
            raise ValueError("Missing /models/server.json; no model is downloaded automatically")
        config = json.loads(source.read_text())
        # Pin executable/cwd. This server is inference-only: never enable its optional
        # host tools, MCP processes, image generation or acquisition settings.
        allowed = {"args", "tokenizer", "model_name"}
        if not isinstance(config, dict) or set(config) - allowed:
            raise ValueError("server.json accepts only args, tokenizer and model_name")
        if not isinstance(config.get("args"), list) or not all(isinstance(x, str) for x in config["args"]):
            raise ValueError("args must be a list of engine argument strings")
        tokenizer = Path(config.get("tokenizer", ""))
        if not tokenizer.is_absolute() or not tokenizer.is_relative_to("/models") or ".." in tokenizer.parts:
            raise ValueError("tokenizer must be a path under /models")
        config.update(exe=str(ROOT / "build-hip/strata"), cwd=str(ROOT), backend="hip")
        Path("/tmp/server.json").write_text(json.dumps(config))
        args = ["--engine", "strata", "--config", "/tmp/server.json"]
    else:
        raise ValueError("Expected devices, smoke or serve")
    # Private internal container network only; no published host port.
    os.execv("/opt/venv/bin/python3", ["python3", "-m", "serve.server", *args,
             "--host", "0.0.0.0", "--port", "8080", "--no-api-key"])


if __name__ == "__main__":
    try:
        main()
    except (ValueError, OSError) as error:
        sys.exit(f"aibox: {error}")
