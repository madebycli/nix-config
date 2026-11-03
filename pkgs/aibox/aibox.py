#!/usr/bin/env python3
"""Rootless AI containers. Models are acquired only through explicit fetch/legacy manager actions."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import time
import urllib.error
import urllib.request

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
    digest.update(json.dumps({k: v for k, v in cfg.items() if k not in ("defaultProfile", "contextSize")}, sort_keys=True).encode())
    return "localhost/nx-ai-strata:" + digest.hexdigest()[:20]


def ensure_image(image):
    if not exists("image", image):
        command = "aibox prepare-ui" if "nx-ai-manager" in image else "aibox prepare --strata"
        raise ValueError(f"Image missing: {image}. Run {command}")


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


def ui_binding(data):
    """Return only an explicitly published loopback UI, never a LAN binding."""
    ports = (data or {}).get("NetworkSettings", {}).get("Ports", {}) or {}
    bindings = ports.get("8080/tcp") or []
    if not bindings:
        return None
    if any(p.get("HostIp") != "127.0.0.1" for p in bindings):
        raise ValueError("Refusing UI with a non-loopback port binding")
    port = str(bindings[0].get("HostPort", ""))
    if not port.isdigit() or not 1024 <= int(port) <= 65535:
        raise ValueError("Invalid UI port in container metadata")
    return f"http://127.0.0.1:{port}"


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


def wait_for_ui(url, timeout=30):
    # Never send a localhost probe through HTTP_PROXY or follow a redirect away
    # from the selected local service.
    class NoRedirect(urllib.request.HTTPRedirectHandler):
        def redirect_request(self, req, fp, code, msg, headers, newurl):
            return None

    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), NoRedirect())
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            with opener.open(url + "/api/health", timeout=1) as response:
                data = json.loads(response.read(65536))
            if not isinstance(data, dict) or data.get("ok") is not True or "backend" not in data or "engine" not in data:
                raise ValueError("The selected port did not answer as Strata")
            return data
        except (urllib.error.URLError, TimeoutError, ConnectionError, json.JSONDecodeError):
            time.sleep(0.25)
    raise ValueError(f"UI is not ready at {url}; check aibox logs and retry aibox ui. The container was left running")


def manager_image(cfg):
    support = Path(os.environ["AIBOX_SUPPORT"])
    digest = hashlib.sha256(image_name(cfg).encode())
    for name in ("ManagerContainerfile", "manager-bundle.py"):
        digest.update((support / name).read_bytes())
    return "localhost/nx-ai-manager:" + digest.hexdigest()[:20]


def prepare_ui(cfg):
    ensure_image(image_name(cfg))
    support = os.environ["AIBOX_SUPPORT"]
    run("build", "--tag", manager_image(cfg), "--file", f"{support}/ManagerContainerfile",
        "--build-arg", f"ENGINE_IMAGE={image_name(cfg)}",
        "--build-arg", f"GPU_ARCH={cfg['gpuArch']}", support)
    print("Full Strata app prepared. No model weights downloaded; no HIP recompile.")


def manager_state(cfg):
    # Keep state adjacent to models, never in the coding workspace or host home.
    models = Path(cfg["modelDirectory"]).expanduser()
    models.mkdir(mode=0o700, parents=True, exist_ok=True)
    models = safe_directory(models)
    state = models.parent / "manager"
    state.mkdir(mode=0o700, parents=True, exist_ok=True)
    state = safe_directory(state)
    if state.is_relative_to(models) or models.is_relative_to(state):
        raise ValueError("Manager state and models must be separate directories")
    return state, models


def start_ui(cfg, port):
    ensure_image(manager_image(cfg))
    devices = gpu_args(cfg)
    state, models = manager_state(cfg)
    ensure_network()
    # Management needs outbound access for explicit model downloads. Coding
    # containers remain on NETWORK only. No host network or engine socket.
    outbound = "nx-ai-downloads"
    if not exists("network", outbound):
        run("network", "create", "--label", f"{LABEL}=true", outbound)
    net = json.loads(run("network", "inspect", outbound, capture=True).stdout)[0]
    if net.get("internal") or net.get("labels", {}).get(LABEL) != "true":
        raise ValueError("Refusing management network without the expected policy/label")
    old = owned_server()
    if old and old.get("State", {}).get("Running"):
        raise ValueError("Inference is running. Run aibox stop before opening the model manager")
    if old:
        run("rm", SERVER)
    run(*base_run(SERVER), "--detach", "--network-alias=strata",
        "--network", outbound, "--label", f"{LABEL}.mode=manager",
        "--userns=keep-id", "--user", f"{os.getuid()}:{os.getgid()}", *devices,
        "--publish", f"127.0.0.1:{port}:8080",
        "--mount", f"type=bind,src={state},target=/state,bind-nonrecursive",
        "--mount", f"type=bind,src={models},target=/models,bind-nonrecursive",
        manager_image(cfg))


def ui(cfg, port=8766, no_open=False):
    if not 1024 <= port <= 65535:
        raise ValueError("UI port must be between 1024 and 65535")
    data = owned_server()
    if data and data.get("State", {}).get("Running"):
        if data.get("Config", {}).get("Labels", {}).get(f"{LABEL}.mode") != "manager":
            raise ValueError("Private inference is running. Run aibox stop, then aibox ui")
        url = ui_binding(data)
        if url != f"http://127.0.0.1:{port}":
            raise ValueError(f"UI is already running at {url}; use that port or stop it first")
    else:
        start_ui(cfg, port)
        url = f"http://127.0.0.1:{port}"
    wait_for_ui(url)
    print(f"Strata model manager: {url}  |  stop with: aibox stop")
    print("Choose/download a model in Models. Nothing is loaded automatically by aibox.")
    if not no_open:
        try:
            result = subprocess.run(["xdg-open", url], check=False, timeout=10,
                                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            if result.returncode:
                print("Browser could not be opened automatically; open the URL above.")
        except (OSError, subprocess.TimeoutExpired):
            print("Browser could not be opened automatically; open the URL above.")


def profiles():
    return json.loads((Path(os.environ["AIBOX_SUPPORT"]) / "profiles.json").read_text())


def profile(cfg, name=None):
    name = name or cfg.get("defaultProfile", "qwen27-iq4xs")
    catalog = profiles()
    if name not in catalog:
        raise ValueError(f"Unknown profile {name!r}; choose from: {', '.join(catalog)}")
    return name, catalog[name]


def profile_directory(cfg, name, *, create=False):
    # Dedicated directories, separate from the legacy Strata manager. Reject
    # symlinks so neither fetching nor serving can escape modelDirectory.
    root = Path(cfg["modelDirectory"]).expanduser()
    if create:
        root.mkdir(mode=0o700, parents=True, exist_ok=True)
    root = safe_directory(root)
    path = root / name
    if path.is_symlink():
        raise ValueError("Profile directory must not be a symlink")
    if create:
        path.mkdir(mode=0o700, exist_ok=True)
    path = safe_directory(path)
    if path.parent != root:
        raise ValueError("Profile directory must be directly inside modelDirectory")
    return path


def verify_file(path, item):
    if path.is_symlink() or not path.is_file() or path.stat().st_size != item["size"]:
        raise ValueError(f"Missing/incomplete model file: {path}. Run aibox fetch PROFILE")
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(8 * 1024 * 1024), b""):
            digest.update(chunk)
    if digest.hexdigest() != item["sha256"]:
        raise ValueError(f"SHA256 mismatch: {path}; file was not accepted")


def profile_files(cfg, name, *, verify=True, vision=True):
    name, entry = profile(cfg, name)
    directory = profile_directory(cfg, name)
    files = [item for item in entry["files"] if vision or item["role"] == "model"]
    if verify:
        for item in files:
            verify_file(directory / item["name"], item)
    return directory, {item["role"]: item for item in files}


def fetch_profile(cfg, name=None):
    name, entry = profile(cfg, name)
    directory = profile_directory(cfg, name, create=True)
    print(f"{entry['name']}\n{entry['provenance']}", flush=True)
    for item in entry["files"]:
        dest = directory / item["name"]
        if dest.exists() or dest.is_symlink():
            verify_file(dest, item)
            print(f"Already verified: {dest.name}", flush=True)
            continue
        partial = dest.with_name(dest.name + ".part")
        if partial.is_symlink() or (partial.exists() and not partial.is_file()):
            raise ValueError("Download target must be a regular file, not a symlink")
        if partial.exists() and partial.stat().st_size > item["size"]:
            raise ValueError(f"Oversized partial file: {partial}; remove it before retrying")
        if not partial.exists() or partial.stat().st_size != item["size"]:
            url = f"https://huggingface.co/{item['repo']}/resolve/{item['revision']}/{item['name']}"
            subprocess.run(["curl", "--fail", "--location", "--proto", "=https",
                            "--proto-redir", "=https", "--retry", "3", "--continue-at", "-",
                            "--output", str(partial), url], check=True)
        verify_file(partial, item)
        partial.chmod(0o600)
        partial.replace(dest)
        print(f"SHA256 verified: {dest.name}", flush=True)
    print(f"Ready on disk. Start explicitly: aibox ui --profile {name}")


def llama_image(cfg):
    support = Path(os.environ["AIBOX_SUPPORT"])
    digest = hashlib.sha256()
    for name in ("LlamaContainerfile", "require-mtp.py"):
        digest.update((support / name).read_bytes())
    digest.update(json.dumps({k: cfg[k] for k in ("gpuArch", "hipBaseImage", "buildJobs")}, sort_keys=True).encode())
    return "localhost/nx-ai-llama:" + digest.hexdigest()[:20]


def prepare_llama(cfg):
    run("load", "--input", os.environ["AIBOX_AGENT_ARCHIVE"])
    support = os.environ["AIBOX_SUPPORT"]
    run("build", "--tag", llama_image(cfg), "--file", f"{support}/LlamaContainerfile",
        "--build-arg", f"BASE={cfg['hipBaseImage']}",
        "--build-arg", f"GPU_ARCH={cfg['gpuArch']}",
        "--build-arg", f"BUILD_JOBS={cfg['buildJobs']}", support)
    print("Prism llama.cpp HIP runtime and embedded UI prepared. No models downloaded.")


def llama_server_args(cfg, name, *, vision=True):
    _, files = profile_files(cfg, name, verify=False, vision=vision)
    context = cfg.get("contextSize", 16384)
    if type(context) is not int or not 2048 <= context <= 262144:
        raise ValueError("contextSize must be an integer between 2048 and 262144")
    args = ["--model", f"/models/{files['model']['name']}", "--alias", "local",
            "--host", "0.0.0.0", "--port", "8080", "--ctx-size", str(context),
            "--parallel", "1", "--batch-size", "256", "--ubatch-size", "128",
            "--device", "ROCm0", "--gpu-layers", "999", "--fit", "off",
            "--flash-attn", "on", "--cache-type-k", "q8_0", "--cache-type-v", "q8_0",
            "--spec-type", "draft-mtp", "--spec-draft-n-max", "2",
            "--spec-draft-n-min", "0", "--spec-draft-p-min", "0",
            "--spec-draft-device", "ROCm0", "--spec-draft-ngl", "999",
            "--spec-draft-type-k", "q8_0", "--spec-draft-type-v", "q8_0",
            "--load-mode", "none", "--jinja", "--temp", "1.0",
            "--top-p", "0.95", "--top-k", "20", "--min-p", "0.05"]
    if vision:
        args += ["--mmproj", f"/models/{files['projector']['name']}"]
    return args


def wait_for_llama(timeout=180):
    deadline = time.monotonic() + timeout
    probe = "import urllib.request; print(urllib.request.urlopen('http://127.0.0.1:8080/health', timeout=1).read().decode())"
    while time.monotonic() < deadline:
        data = owned_server()
        if not data or not data.get("State", {}).get("Running"):
            run("logs", "--tail=100", SERVER, check=False)
            raise ValueError("Model server exited; see logs above. No settings were weakened or model changed")
        result = run("exec", SERVER, "python3", "-I", "-c", probe, check=False, capture=True)
        if result.returncode == 0:
            logs = run("logs", SERVER, capture=True)
            if "speculative decoding enabled: draft-mtp" not in logs.stdout + logs.stderr:
                run("stop", "--time=10", SERVER)
                raise ValueError("MTP activation was not confirmed; server stopped")
            return
        time.sleep(1)
    raise ValueError("Model still loading; inspect aibox logs/status. Container left running; no success claimed")


def start_llama(cfg, name=None, *, port=None, no_open=True, vision=True):
    name, entry = profile(cfg, name)
    if port is not None and (type(port) is not int or not 1024 <= port <= 65535):
        raise ValueError("UI port must be between 1024 and 65535")
    old = owned_server()
    if old and old.get("State", {}).get("Running"):
        labels = old.get("Config", {}).get("Labels", {})
        if (port is not None and labels.get(f"{LABEL}.mode") == "llama"
                and labels.get(f"{LABEL}.profile") == name
                and ui_binding(old) == f"http://127.0.0.1:{port}"
                and old.get("Config", {}).get("Cmd") == llama_server_args(cfg, name, vision=vision)):
            wait_for_llama()
            show_llama_ui(port, no_open)
            return
        raise ValueError("Inference is running; run aibox stop before changing profiles, settings or UI mode")
    image = llama_image(cfg)
    if not exists("image", image):
        raise ValueError("Prism HIP runtime missing. Run aibox prepare first")
    # Verify before replacing an existing container; no network downloads on start.
    directory, _ = profile_files(cfg, name, vision=vision)
    server_args = llama_server_args(cfg, name, vision=vision)
    devices = gpu_args(cfg)
    ensure_network()
    if old:
        run("rm", SERVER)
    args = base_run(SERVER) + ["--detach", "--network-alias=strata",
            "--label", f"{LABEL}.mode=llama", "--label", f"{LABEL}.profile={name}",
            "--userns=keep-id", "--user", f"{os.getuid()}:{os.getgid()}", *devices,
            "--env=HIP_VISIBLE_DEVICES=0",
            "--mount", f"type=bind,src={directory},target=/models,ro,bind-nonrecursive"]
    if port is not None:
        args += ["--publish", f"127.0.0.1:{port}:8080"]
    run(*args, image, *server_args)
    print(f"Loading {entry['name']}; context={cfg.get('contextSize', 16384)}, K/V=q8_0, MTP max=2.", flush=True)
    if name == "qwen27-iq4xs":
        print("RX 6800: IQ4_XS + vision + MTP may exceed VRAM. No automatic CPU offload/context reduction.", flush=True)
    wait_for_llama()
    print("Server healthy; draft-mtp initialized. Acceptance/speed must be measured with real requests.")
    if port is not None:
        show_llama_ui(port, no_open)
    else:
        print("Private API: http://strata:8080/v1 inside aibox; no host port published")


def show_llama_ui(port, no_open):
    url = f"http://127.0.0.1:{port}"
    print(f"llama.cpp chat UI: {url} | stop: aibox stop")
    if not no_open:
        try:
            subprocess.run(["xdg-open", url], check=False, timeout=10,
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        except (OSError, subprocess.TimeoutExpired):
            print("Open the URL above manually.")


def agent_args(cfg, project, command):
    path = safe_directory(project, workspace=True, model=cfg["modelDirectory"])
    manager = Path(cfg["modelDirectory"]).expanduser().resolve().parent / "manager"
    if path.is_relative_to(manager) or manager.is_relative_to(path):
        raise ValueError("Workspace and manager state directory must not overlap")
    args = base_run() + ["--rm", "--interactive",
            "--userns=keep-id:uid=1000,gid=1000", "--user=1000:1000",
            "--mount", f"type=bind,src={path},target=/work,bind-nonrecursive",
            "--workdir=/work", "--env=OPENAI_BASE_URL=http://strata:8080/v1",
            "--env=OPENAI_API_KEY=local-only"]
    if sys.stdin.isatty() and sys.stdout.isatty():
        args += ["--tty"]
    # The shell is inside the container. No host command string is evaluated.
    bootstrap = '''umask 077
export HOME
HOME="$(mktemp -d "${TMPDIR:-/tmp}/aibox-home.XXXXXXXX")"
mkdir -p "$HOME/.codex"
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
    return args + [os.environ["AIBOX_AGENT_IMAGE"], "/bin/bash", "-e", "-c", bootstrap, "aibox", *command]


def main():
    parser = argparse.ArgumentParser(prog="aibox", description=__doc__)
    sub = parser.add_subparsers(dest="action", required=True)
    p = sub.add_parser("prepare", help="Load coding image and explicitly build HIP runtime, no models")
    p.add_argument("--agent-only", action="store_true")
    p.add_argument("--strata", action="store_true", help="Prepare legacy Strata instead of Prism llama.cpp")
    p = sub.add_parser("doctor", help="List HIP devices without loading a model")
    p.add_argument("--strata", action="store_true")
    sub.add_parser("models", help="List pinned model profiles; no download")
    for action in ("fetch", "verify"):
        p = sub.add_parser(action, help=("Explicitly download" if action == "fetch" else "Verify") + " a pinned model and its vision projector")
        p.add_argument("profile", nargs="?")
    sub.add_parser("smoke", help="Start the real API in mock mode, without GPU or model")
    sub.add_parser("prepare-ui", help="Build legacy Strata manager on its prepared HIP image, no models")
    p = sub.add_parser("ui", help="Start selected model and open llama.cpp chat UI on localhost")
    p.add_argument("--strata", action="store_true", help="Open legacy Strata manager instead")
    p.add_argument("--profile", choices=("qwen27-iq4xs", "bonsai27-pq2"))
    p.add_argument("--text-only", action="store_true", help="Explicitly omit the vision projector")
    p.add_argument("--port", type=int, default=8766)
    p.add_argument("--no-open", action="store_true", help="Print the address without launching a browser")
    p = sub.add_parser("start", help="Start a pinned model on the private network")
    p.add_argument("--strata", action="store_true")
    p.add_argument("--profile", choices=("qwen27-iq4xs", "bonsai27-pq2"))
    p.add_argument("--text-only", action="store_true")
    for name in ("stop", "status", "logs"):
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
        prepare(cfg, args.agent_only) if args.agent_only or args.strata else prepare_llama(cfg)
    elif args.action == "prepare-ui":
        prepare_ui(cfg)
    elif args.action == "models":
        print(json.dumps({"selected": profile(cfg)[0], "context": cfg.get("contextSize", 16384),
                          "kv_k": "q8_0", "kv_v": "q8_0", "mtp_max": 2, "profiles": profiles()}, indent=2))
    elif args.action == "fetch":
        fetch_profile(cfg, args.profile)
    elif args.action == "verify":
        name, _ = profile(cfg, args.profile)
        profile_files(cfg, name)
        print(f"Verified model and projector: {name}")
    elif args.action == "doctor" and not args.strata:
        image = llama_image(cfg)
        if not exists("image", image):
            raise ValueError("Runtime missing; run aibox prepare")
        probe = base_run()
        probe[probe.index("--network") + 1] = "none"
        run(*probe, "--rm", "--userns=keep-id", "--user", f"{os.getuid()}:{os.getgid()}",
            *gpu_args(cfg), image, "--list-devices")
    elif args.action == "doctor":
        ensure_image(image_name(cfg))
        # Probe has no network and no host file mounts.
        probe = base_run()
        index = probe.index("--network")
        probe[index + 1] = "none"
        run(*probe, "--rm", "--userns=keep-id", "--user", f"{os.getuid()}:{os.getgid()}",
            *gpu_args(cfg), image_name(cfg), "devices")
    elif args.action in ("start", "smoke"):
        if args.action == "smoke" or args.strata:
            start(cfg, smoke=args.action == "smoke")
        else:
            start_llama(cfg, args.profile, vision=not args.text_only)
    elif args.action == "ui":
        if args.strata:
            ui(cfg, port=args.port, no_open=args.no_open)
        else:
            start_llama(cfg, args.profile, port=args.port, no_open=args.no_open, vision=not args.text_only)
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
            run("stop", "--time=60", SERVER)
    elif args.action == "logs":
        if not owned_server():
            raise ValueError("Inference has not been started")
        run("logs", "--tail=100", SERVER)
    else:
        data = owned_server()
        print(json.dumps({"inference": data.get("State") if data else None,
                          "image_prepared": exists("image", image_name(cfg)),
                          "llama_image_prepared": exists("image", llama_image(cfg)),
                          "profile": (data or {}).get("Config", {}).get("Labels", {}).get(f"{LABEL}.profile"),
                          "command": (data or {}).get("Config", {}).get("Cmd"),
                          "model_config_present": (Path(cfg["modelDirectory"]).expanduser() / "server.json").is_file(),
                          "ui": ui_binding(data) if data else None,
                          "api": "http://strata:8080/v1 (container network only)"}, indent=2))
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except (ValueError, KeyError, OSError, subprocess.SubprocessError) as error:
        sys.exit(f"aibox: {error}")
