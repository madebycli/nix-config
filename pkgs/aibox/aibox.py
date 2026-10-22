#!/usr/bin/env python3
"""Unprivileged container controller. No model acquisition and no implicit pulls."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys

NETWORK = "nx-ai-private"
SERVER = "nx-ai-inference"
LABEL = "io.nix-config.aibox"


def run(*args, check=True, capture=False):
    return subprocess.run(["podman", "--runtime=crun", *map(str, args)], check=check,
                          text=True, capture_output=capture)


def exists(kind, name):
    result = run(kind, "exists", name, check=False, capture=True)
    if result.returncode not in (0, 1):
        raise ValueError(result.stderr.strip() or "Podman is unavailable")
    return result.returncode == 0


def safe_directory(value, *, workspace=False, model=None):
    path = Path(value).expanduser().resolve(strict=True)
    if not path.is_dir() or any(c in str(path) for c in ",:\n\r"):
        raise ValueError("Expected a directory without commas, colons or newlines")
    home = Path.home().resolve()
    if path == home or path in home.parents:
        raise ValueError("Share a dedicated subdirectory, never your home or its parent")
    if path.stat().st_uid != os.getuid() or str(path) in ("/tmp", "/var", "/usr", "/opt", "/srv", "/mnt", "/media"):
        raise ValueError("Share a dedicated directory owned by your user")
    if any(path.is_relative_to(p) for p in ("/etc", "/nix", "/run", "/dev", "/proc", "/sys", "/boot")):
        raise ValueError("System directories cannot be shared")
    if workspace and model:
        models = Path(model).expanduser().resolve()
        if path.is_relative_to(models) or models.is_relative_to(path):
            raise ValueError("Workspace and model directory must not overlap")
    return path


def load_config():
    path = Path(os.environ.get("AIBOX_CONFIG", "/etc/aibox.json"))
    if not path.is_file():
        raise ValueError("Enable my.features.local-ai.enable and rebuild first")
    return json.loads(path.read_text())


def image_name(cfg):
    # Changes to the Containerfile, entry point or build options select a new image.
    support = Path(os.environ["AIBOX_SUPPORT"])
    digest = hashlib.sha256()
    for p in (support / "Containerfile", support / "entrypoint.py"):
        digest.update(p.read_bytes())
    digest.update(json.dumps(cfg, sort_keys=True).encode())
    return "localhost/nx-ai-strata:" + digest.hexdigest()[:20]


def ensure_image(image):
    if not exists("image", image):
        raise ValueError(f"Image missing: {image}. Run aibox prepare first")


def ensure_network():
    if not exists("network", NETWORK):
        run("network", "create", "--internal", "--label", f"{LABEL}=true", NETWORK)
    data = json.loads(run("network", "inspect", NETWORK, capture=True).stdout)[0]
    if not data.get("internal") or data.get("labels", {}).get(LABEL) != "true":
        raise ValueError("Refusing an existing network without the expected internal policy/label")


def base_run(name=None):
    args = ["run", "--pull=never", "--read-only", "--cap-drop=ALL",
            "--security-opt=no-new-privileges", "--http-proxy=false",
            "--pids-limit=2048", "--shm-size=1g",
            "--tmpfs=/tmp:rw,nosuid,nodev,mode=1777", "--network", NETWORK,
            "--no-hosts", "--label", f"{LABEL}=true"]
    if name:
        args += ["--name", name]
    return args


def gpu_args(cfg):
    devices = ["/dev/kfd", cfg["renderDevice"]]
    for device in devices:
        if not Path(device).exists() or not os.access(device, os.R_OK | os.W_OK):
            raise ValueError(f"No read/write access to {device}; check groups and log in again")
    return ["--group-add=keep-groups", *[f"--device={x}" for x in devices]]


def owned_server():
    if not exists("container", SERVER):
        return None
    data = json.loads(run("inspect", SERVER, capture=True).stdout)[0]
    if data.get("Config", {}).get("Labels", {}).get(LABEL) != "true":
        raise ValueError("Container name is already used by another application")
    return data


def prepare(cfg, agent_only=False):
    run("load", "--input", os.environ["AIBOX_AGENT_ARCHIVE"])
    if agent_only:
        return
    support = os.environ["AIBOX_SUPPORT"]
    run("build", "--tag", image_name(cfg), "--file", f"{support}/Containerfile",
        "--build-arg", f"BASE={cfg['hipBaseImage']}",
        "--build-arg", f"GPU_ARCH={cfg['gpuArch']}",
        "--build-arg", f"BUILD_JOBS={cfg['buildJobs']}", support)
    print("Runtime prepared. No models downloaded. Next: aibox doctor")


def start(cfg, smoke=False):
    ensure_image(image_name(cfg))
    models = None if smoke else safe_directory(cfg["modelDirectory"])
    if models and not (models / "server.json").is_file():
        raise ValueError("No server.json in modelDirectory. Supply a model/config later; no download attempted")
    devices = [] if smoke else gpu_args(cfg)
    ensure_network()
    old = owned_server()
    if old and old.get("State", {}).get("Running"):
        raise ValueError("Inference is already running; use aibox stop before changing it")
    if old:
        run("rm", SERVER)
    args = base_run(SERVER) + ["--detach", "--network-alias=strata",
            "--userns=keep-id", "--user", f"{os.getuid()}:{os.getgid()}", *devices]
    if models:
        args += ["--mount", f"type=bind,src={models},target=/models,ro,bind-nonrecursive"]
    run(*args, image_name(cfg), "smoke" if smoke else "serve")
    print("Mock API started (no AI model)." if smoke else "Inference started. Check aibox status/logs for readiness.")
    print("Private API: http://strata:8080/v1 inside aibox; no host port published")


def agent_args(cfg, project, command):
    path = safe_directory(project, workspace=True, model=cfg["modelDirectory"])
    args = base_run() + ["--rm", "--interactive",
            "--userns=keep-id:uid=1000,gid=1000", "--user=1000:1000",
            "--tmpfs=/home/agent:rw,nosuid,nodev,uid=1000,gid=1000,mode=0700",
            "--mount", f"type=bind,src={path},target=/work,bind-nonrecursive",
            "--workdir=/work", "--env=OPENAI_BASE_URL=http://strata:8080/v1",
            "--env=OPENAI_API_KEY=local-only"]
    if sys.stdin.isatty() and sys.stdout.isatty():
        args += ["--tty"]
    # The shell is inside the container. No host command string is evaluated.
    bootstrap = '''mkdir -p "$HOME/.codex"
cp /share/aibox/SKILLS.md "$HOME/.codex/AGENTS.md"
cat > "$HOME/.codex/config.toml" <<'TOML'
model_provider = "strata"
model = "local"
[model_providers.strata]
name = "Local Strata"
base_url = "http://strata:8080/v1"
wire_api = "responses"
TOML
exec "$@"
'''
    return args + [os.environ["AIBOX_AGENT_IMAGE"], "/bin/bash", "-c", bootstrap, "aibox", *command]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="action", required=True)
    p = sub.add_parser("prepare", help="Load coding image and explicitly build HIP runtime, no models")
    p.add_argument("--agent-only", action="store_true")
    sub.add_parser("doctor", help="Run Strata's GPU device probe without a model")
    sub.add_parser("smoke", help="Start the real API in mock mode, without GPU or model")
    for name in ("start", "stop", "status", "logs"):
        sub.add_parser(name)
    p = sub.add_parser("shell", help="Open offline coding shell sharing only PROJECT")
    p.add_argument("project")
    p = sub.add_parser("exec", help="Run a command inside the offline coding container")
    p.add_argument("project")
    p.add_argument("command", nargs=argparse.REMAINDER)
    args = parser.parse_args()
    if os.getuid() == 0:
        raise ValueError("Run aibox as your normal user, without sudo")
    cfg = load_config()
    if args.action == "prepare":
        prepare(cfg, args.agent_only)
    elif args.action == "doctor":
        ensure_image(image_name(cfg))
        # Probe has no network and no host file mounts.
        probe = base_run()
        index = probe.index("--network")
        probe[index + 1] = "none"
        run(*probe, "--rm", "--userns=keep-id", "--user", f"{os.getuid()}:{os.getgid()}",
            *gpu_args(cfg), image_name(cfg), "devices")
    elif args.action in ("start", "smoke"):
        start(cfg, smoke=args.action == "smoke")
    elif args.action in ("shell", "exec"):
        ensure_image(os.environ["AIBOX_AGENT_IMAGE"])
        ensure_network()
        command = ["/bin/bash"] if args.action == "shell" else args.command
        if command and command[0] == "--":
            command = command[1:]
        if not command:
            raise ValueError("Expected a command after PROJECT")
        result = run(*agent_args(cfg, args.project, command), check=False)
        return result.returncode
    elif args.action == "stop":
        if owned_server():
            run("stop", "--time=20", SERVER)
    elif args.action == "logs":
        if not owned_server():
            raise ValueError("Inference has not been started")
        run("logs", "--tail=100", SERVER)
    else:
        data = owned_server()
        print(json.dumps({"inference": data.get("State") if data else None,
                          "image_prepared": exists("image", image_name(cfg)),
                          "model_config_present": (Path(cfg["modelDirectory"]).expanduser() / "server.json").is_file(),
                          "api": "http://strata:8080/v1 (container network only)"}, indent=2))
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except (ValueError, KeyError, OSError, subprocess.SubprocessError) as error:
        sys.exit(f"aibox: {error}")
