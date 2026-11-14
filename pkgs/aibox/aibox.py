#!/usr/bin/env python3
"""Rootless AI containers. Models are acquired only through explicit fetch/legacy manager actions."""
import argparse
import hashlib
import json
import os
import re
import shutil
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
        command = ("aibox prepare --dev" if "nx-ai-dev" in image else
                   "aibox prepare-ui" if "nx-ai-manager" in image else
                   "aibox prepare --agent-only" if "nx-ai-agent" in image else "aibox prepare --strata")
        raise ValueError(f"Image missing: {image}. Run {command}")


def ensure_network():
    if not exists("network", NETWORK):
        run("network", "create", "--internal", "--label", f"{LABEL}=true", NETWORK)
    data = json.loads(run("network", "inspect", NETWORK, capture=True).stdout)[0]
    if not data.get("internal") or data.get("labels", {}).get(LABEL) != "true":
        raise ValueError("Refusing an existing network without the expected internal policy/label")


OUTBOUND = "nx-ai-downloads"


def ensure_outbound_network():
    if not exists("network", OUTBOUND):
        run("network", "create", "--label", f"{LABEL}=true", OUTBOUND)
    net = json.loads(run("network", "inspect", OUTBOUND, capture=True).stdout)[0]
    if net.get("internal") or net.get("labels", {}).get(LABEL) != "true":
        raise ValueError("Refusing outbound network without the expected policy/label")
    return OUTBOUND


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
    outbound = ensure_outbound_network()
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


# Assumed main + MTP draft KV bytes per token (16 attention layers); planning estimate only.
KVMEM_KV_BYTES_PER_TOKEN = {"q8_0": 36864, "q5_0": 23808, "q4_0": 20608, "k8v4": 28800}


def kv_types(dtype):
    """(main K, main V, draft). k8v4 = K q8_0 / V q4_0, the mixed form KVMem validates.
    The tiny MTP draft cache stays q8_0 when main is 4-bit; RDNA2 needs a quantized draft cache."""
    if dtype == "k8v4":
        return "q8_0", "q4_0", "q8_0"
    return dtype, dtype, ("q8_0" if dtype == "q4_0" else dtype)
KVMEM_COMPUTE_OVERHEAD_MIB = 1700  # measured on nyx (lc256-iq3): ~14.5 GiB server peak (15.26 GiB total minus ~0.73 GiB desktop) minus weights and KV pool
KVMEM_UI = "/opt/kvmem-build/share/kvmem/ui"


def kvmem_image(cfg):
    support = Path(os.environ["AIBOX_SUPPORT"])
    digest = hashlib.sha256((support / "KvmemContainerfile").read_bytes())
    digest.update(json.dumps({k: cfg[k] for k in ("gpuArch", "hipBaseImage", "buildJobs")}, sort_keys=True).encode())
    return "localhost/nx-ai-kvmem:" + digest.hexdigest()[:20]


def prepare_kvmem(cfg):
    run("load", "--input", os.environ["AIBOX_AGENT_ARCHIVE"])
    support = os.environ["AIBOX_SUPPORT"]
    run("build", "--tag", kvmem_image(cfg), "--file", f"{support}/KvmemContainerfile",
        "--build-arg", f"BASE={cfg['hipBaseImage']}",
        "--build-arg", f"GPU_ARCH={cfg['gpuArch']}",
        "--build-arg", f"BUILD_JOBS={cfg['buildJobs']}", support)
    print("KVMem long-context runtime prepared (separate image; Prism runtime unchanged). No models downloaded.")


def longcontext_presets():
    data = json.loads((Path(os.environ["AIBOX_SUPPORT"]) / "longcontext.json").read_text())
    return {k: v for k, v in data.items() if not k.startswith("_")}


def longcontext_settings(cfg, preset, *, allow_experimental=False):
    """Explicit preset plus optional Nix overrides. Never adjusted to fit memory."""
    presets = longcontext_presets()
    if preset not in presets:
        raise ValueError(f"Unknown long-context preset {preset!r}; choose from: {', '.join(presets)}")
    settings = dict(presets[preset])
    overrides = cfg.get("longContext") or {}
    for key in ("gpuBudget", "genReserve", "hostKvMiB", "containerRamMiB"):
        if overrides.get(key) is not None:
            settings[key] = overrides[key]
    settings["kvDtype"] = overrides.get("kvDtype") or settings.get("kvDtype", "q8_0")
    if settings["kvDtype"] not in KVMEM_KV_BYTES_PER_TOKEN:
        raise ValueError("kvDtype must be one of q8_0 (default), q5_0, k8v4, q4_0; it is never changed automatically")
    settings["computeOverheadMiB"] = overrides.get("computeOverheadMiB", KVMEM_COMPUTE_OVERHEAD_MIB)
    settings["imageMaxTokens"] = overrides.get("imageMaxTokens") or 512
    settings["imageMinTokens"] = overrides.get("imageMinTokens") or 0
    settings["vramHeadroomMiB"] = overrides.get("vramHeadroomMiB", 256)
    settings["ramHeadroomMiB"] = overrides.get("ramHeadroomMiB", 2048)
    for key in ("workspace", "gpuBudget", "genReserve", "hostKvMiB", "containerRamMiB",
                "vramHeadroomMiB", "ramHeadroomMiB", "computeOverheadMiB", "imageMaxTokens", "imageMinTokens"):
        if type(settings[key]) is not int or settings[key] < 0:
            raise ValueError(f"{key} must be a non-negative integer")
    if settings["gpuBudget"] % 128 or settings["genReserve"] % 128 or settings["gpuBudget"] < 4096 or settings["genReserve"] < 1024:
        raise ValueError("gpuBudget/genReserve must be multiples of the 128-token KVMem block (>= 4096 / >= 1024)")
    if settings["gpuBudget"] + settings["genReserve"] > settings["workspace"]:
        raise ValueError("gpuBudget + genReserve must not exceed the logical workspace")
    if settings["hostKvMiB"] < 1 or settings["containerRamMiB"] <= settings["hostKvMiB"]:
        raise ValueError("containerRamMiB must be larger than hostKvMiB")
    if settings["experimental"] and not allow_experimental:
        raise ValueError(f"Preset {preset} is experimental (host KV is likely to exceed this machine's RAM); "
                         "pass --allow-experimental to attempt it")
    settings["preset"] = preset
    return settings


def longcontext_profile(cfg, preset, requested=None):
    """Profile of a preset. A preset never silently switches model: a mismatching request is refused."""
    wanted = longcontext_presets().get(preset, {}).get("profile", "qwen27-iq4xs")
    if requested and requested != wanted:
        raise ValueError(f"Preset {preset} is defined for {wanted}, not {requested}")
    if wanted not in profiles():
        raise ValueError(f"Preset {preset} needs profile {wanted}, whose pinned files are not in profiles.json yet; "
                         "see docs/LOCAL-AI-LONGCONTEXT.md. Nothing is substituted")
    return wanted


def kvmem_server_args(cfg, name, settings, *, vision=True):
    _, files = profile_files(cfg, name, verify=False, vision=vision)
    args = ["--model", f"/models/{files['model']['name']}", "--alias", "local",
            "--host", "0.0.0.0", "--port", "8080", "--ctx-size", str(settings["workspace"]),
            "--parallel", "1", "--batch-size", "256", "--ubatch-size", "128",
            "--device", "ROCm0", "--gpu-layers", "999", "--load-mode", "none",
            "--flash-attn", "on", "--cache-type-k", kv_types(settings["kvDtype"])[0],
            "--cache-type-v", kv_types(settings["kvDtype"])[1],
            "--kvmem", "--kvmem-budget", str(settings["gpuBudget"]),
            "--kvmem-gen-reserve", str(settings["genReserve"]),
            "--kvmem-block-tokens", "128", "--kvmem-query-policy", "user",
            "--kvmem-host-mib", str(settings["hostKvMiB"]),
            "--spec-type", "draft-mtp", "--spec-draft-n-max", "2",
            "--spec-kv-dtype", kv_types(settings["kvDtype"])[2], "--kvmem-mtp-state", "replay",
            "--jinja", "--webui", "--ui-dir", KVMEM_UI]
    if vision:
        # Projector on CPU: keeps it out of the tight 16 GiB; image encoding is slower.
        args += ["--mmproj", f"/models/{files['projector']['name']}", "--no-mmproj-offload",
                 "--image-max-tokens", str(settings["imageMaxTokens"])]
        if settings["imageMinTokens"]:
            args += ["--image-min-tokens", str(settings["imageMinTokens"])]
    return args


def meminfo_mib():
    values = {}
    for line in Path("/proc/meminfo").read_text().splitlines():
        key, _, rest = line.partition(":")
        values[key] = int(rest.split()[0]) // 1024
    return values


def vram_mib(cfg):
    base = Path("/sys/class/drm") / Path(cfg["renderDevice"]).name / "device"
    try:
        return (int((base / "mem_info_vram_total").read_text()) >> 20,
                int((base / "mem_info_vram_used").read_text()) >> 20)
    except (OSError, ValueError):
        return None


def longcontext_plan(cfg, name, settings, *, vision=True):
    """Explicit memory plan. Returns (plan, problems); the caller refuses on problems."""
    _, files = profile_files(cfg, name, verify=False, vision=vision)
    weights = -(-files["model"]["size"] // (1 << 20))
    pool = settings["gpuBudget"] + settings["genReserve"]
    kv = -(-pool * KVMEM_KV_BYTES_PER_TOKEN[settings["kvDtype"]] // (1 << 20))
    need_vram = weights + kv + settings["computeOverheadMiB"] + settings["vramHeadroomMiB"]
    plan = {"profile": name, "preset": settings["preset"], "workspace_tokens": settings["workspace"],
            "vram_working_pool_tokens": pool, "estimate_mib": {"weights": weights, "kv_pool": kv,
            "compute_overhead_assumed": settings["computeOverheadMiB"], "headroom": settings["vramHeadroomMiB"],
            "vram_total_needed": need_vram, "host_kv_quota": settings["hostKvMiB"],
            "container_ram_cap": settings["containerRamMiB"]},
            "vision": "cpu projector" if vision else "off",
            "kv_dtype": settings["kvDtype"],
            "note": "Estimates only; weights from the pinned file size, KV from an assumed per-token size incl. MTP. Verify with aibox status/logs on nyx."}
    problems = []
    vram = vram_mib(cfg)
    if vram is None:
        plan["vram_free_mib"] = None
        plan["warning"] = "VRAM could not be read from sysfs; fit is unverified"
    else:
        plan["vram_free_mib"] = vram[0] - vram[1]
        if vram[0] - vram[1] < need_vram:
            problems.append(f"VRAM: ~{need_vram} MiB needed (weights {weights} + KV pool {kv} + compute "
                            f"{settings['computeOverheadMiB']} + headroom {settings['vramHeadroomMiB']}), "
                            f"{vram[0] - vram[1]} MiB free of {vram[0]}. Close GPU users or choose a smaller "
                            "gpuBudget/genReserve explicitly; nothing is reduced or offloaded automatically")
    try:
        mem = meminfo_mib()
        plan["ram_available_mib"] = mem["MemAvailable"]
        plan["host_swap_total_mib"] = mem.get("SwapTotal", 0)
        if mem["MemAvailable"] < settings["containerRamMiB"] + settings["ramHeadroomMiB"]:
            problems.append(f"RAM: container cap {settings['containerRamMiB']} MiB + headroom "
                            f"{settings['ramHeadroomMiB']} MiB exceeds MemAvailable {mem['MemAvailable']} MiB. "
                            "Choose a smaller workspace preset or free memory; swap is never used for KV")
    except (OSError, KeyError, ValueError):
        plan["ram_available_mib"] = None
    return plan, problems


def llama_server_args(cfg, name, *, vision=True):
    _, files = profile_files(cfg, name, verify=False, vision=vision)
    context = cfg.get("contextSize", 16384)
    if type(context) is not int or not 2048 <= context <= 262144:
        raise ValueError("contextSize must be an integer between 2048 and 262144")
    dtype = cfg.get("kvCacheType") or "q8_0"
    if dtype not in ("q8_0", "k8v4", "q4_0"):
        raise ValueError("kvCacheType must be q8_0 (default), k8v4 or q4_0; it is never changed automatically")
    kv = kv_types(dtype)
    args = ["--model", f"/models/{files['model']['name']}", "--alias", "local",
            "--host", "0.0.0.0", "--port", "8080", "--ctx-size", str(context),
            "--parallel", "1", "--batch-size", "256", "--ubatch-size", "128",
            "--device", "ROCm0", "--gpu-layers", "999", "--fit", "off",
            "--flash-attn", "on", "--cache-type-k", kv[0], "--cache-type-v", kv[1],
            "--spec-type", "draft-mtp", "--spec-draft-n-max", "2",
            "--spec-draft-n-min", "0", "--spec-draft-p-min", "0",
            "--spec-draft-device", "ROCm0", "--spec-draft-ngl", "999",
            "--spec-draft-type-k", kv[2], "--spec-draft-type-v", kv[2],
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


def wait_for_kvmem(timeout=300):
    """Ready only when /health is ok and every slot reports an active speculative (MTP) sampler."""
    deadline = time.monotonic() + timeout
    probe = ("import json, urllib.request as u\n"
             "h = json.load(u.urlopen('http://127.0.0.1:8080/health', timeout=2))\n"
             "s = json.load(u.urlopen('http://127.0.0.1:8080/slots', timeout=2))\n"
             "print(json.dumps({'health': h, 'slots': [bool(x.get('speculative')) for x in s]}))")
    while time.monotonic() < deadline:
        data = owned_server()
        if not data or not data.get("State", {}).get("Running"):
            run("logs", "--tail=100", SERVER, check=False)
            raise ValueError("Long-context server exited (see logs above; KVMEM_STARTUP_ERROR lines name the cause). "
                             "No setting was weakened. Roll back with: aibox stop && aibox ui")
        result = run("exec", SERVER, "python3", "-I", "-c", probe, check=False, capture=True)
        if result.returncode == 0:
            state = json.loads(result.stdout)
            if state["health"].get("status") != "ok":
                time.sleep(1)
                continue
            if not state["slots"] or not all(state["slots"]):
                run("stop", "--time=10", SERVER)
                raise ValueError("MTP is not active in the KVMem server; server stopped (no silent fallback)")
            return
        time.sleep(1)
    raise ValueError("Model still loading; inspect aibox logs/status. Container left running; no success claimed")


def start_llama(cfg, name=None, *, port=None, no_open=True, vision=True, long_context=None,
                allow_experimental=False):
    if long_context:
        name = longcontext_profile(cfg, long_context, name)
    name, entry = profile(cfg, name)
    if port is not None and (type(port) is not int or not 1024 <= port <= 65535):
        raise ValueError("UI port must be between 1024 and 65535")
    settings = longcontext_settings(cfg, long_context, allow_experimental=allow_experimental) if long_context else None
    # A long-context preset pins its model explicitly. The pinned KVMem llama.cpp
    # patch series includes PQ2_0 and Bonsai Hadamard/MTP support; no fallback to
    # the Prism server or to a different quantization is permitted.
    server_args = kvmem_server_args(cfg, name, settings, vision=vision) if settings else llama_server_args(cfg, name, vision=vision)
    engine = "kvmem" if settings else "prism"
    old = owned_server()
    if old and old.get("State", {}).get("Running"):
        labels = old.get("Config", {}).get("Labels", {})
        if (port is not None and labels.get(f"{LABEL}.mode") == "llama"
                and labels.get(f"{LABEL}.profile") == name
                and labels.get(f"{LABEL}.engine", "prism") == engine
                and ui_binding(old) == f"http://127.0.0.1:{port}"
                and old.get("Config", {}).get("Cmd") == server_args):
            (wait_for_kvmem if settings else wait_for_llama)()
            show_llama_ui(port, no_open)
            return
        raise ValueError("Inference is running; run aibox stop before changing profiles, settings or UI mode")
    image = kvmem_image(cfg) if settings else llama_image(cfg)
    if not exists("image", image):
        raise ValueError("KVMem runtime missing. Run aibox prepare --kvmem first" if settings
                         else "Prism HIP runtime missing. Run aibox prepare first")
    # Verify before replacing an existing container; no network downloads on start.
    directory, _ = profile_files(cfg, name, vision=vision)
    memory = []
    if settings:
        plan, problems = longcontext_plan(cfg, name, settings, vision=vision)
        print(json.dumps(plan, indent=2), flush=True)
        if problems:
            raise ValueError("Insufficient memory for the requested configuration:\n  - " + "\n  - ".join(problems))
        # Hard container cap; swap equal to the cap means no swapping of KV or weights.
        memory = [f"--memory={settings['containerRamMiB']}m", f"--memory-swap={settings['containerRamMiB']}m"]
    devices = gpu_args(cfg)
    ensure_network()
    if old:
        run("rm", SERVER)
    args = base_run(SERVER) + ["--detach", "--network-alias=strata",
            "--label", f"{LABEL}.mode=llama", "--label", f"{LABEL}.profile={name}",
            "--label", f"{LABEL}.engine={engine}", *memory,
            "--userns=keep-id", "--user", f"{os.getuid()}:{os.getgid()}", *devices,
            "--env=HIP_VISIBLE_DEVICES=0",
            "--mount", f"type=bind,src={directory},target=/models,ro,bind-nonrecursive"]
    if port is not None:
        args += ["--publish", f"127.0.0.1:{port}:8080"]
    run(*args, image, *server_args)
    if settings:
        print(f"Loading {entry['name']} via KVMem: preset={settings['preset']}, workspace={settings['workspace']}, "
              f"GPU pool={settings['gpuBudget']}+{settings['genReserve']}, host KV={settings['hostKvMiB']} MiB, "
              f"KV={settings['kvDtype']}, MTP max=2, vision on CPU.", flush=True)
        print("No automatic context reduction, CPU weight offload or swap. Rollback: aibox stop && aibox ui", flush=True)
        wait_for_kvmem()
        print("Server healthy; MTP sampler active. Run the probe to verify retrieval, tools, vision and speed.")
    else:
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


def dev_image(cfg):
    support = Path(os.environ["AIBOX_SUPPORT"])
    digest = hashlib.sha256()
    for name in ("DevContainerfile", "shot.sh", "SKILLS.md", "longctx_probe.py"):
        digest.update((support / name).read_bytes())
    return "localhost/nx-ai-dev:" + digest.hexdigest()[:20]


def prepare_dev(cfg):
    support = os.environ["AIBOX_SUPPORT"]
    run("build", "--tag", dev_image(cfg), "--file", f"{support}/DevContainerfile", support)
    print("Dev coding image prepared (Debian userland, OpenCode, Chromium, JDK 17). No models downloaded.")


def tools_directory(cfg, workspace):
    """Persistent download area for `aibox shell --dev` (named workspaces have their own)."""
    models = Path(cfg["modelDirectory"]).expanduser().resolve()
    path = ws_root(cfg) / "_tools" / "default"
    path.mkdir(mode=0o700, parents=True, exist_ok=True)
    path = safe_directory(path)
    for other in (models, models.parent / "manager", workspace):
        if path.is_relative_to(other) or other.is_relative_to(path):
            raise ValueError(f"Agent tools directory must not overlap {other}")
    return path


def agent_args(cfg, project, command, *, online=False, full_access=False, dev=False, tools=None, state=None,
               context=None, vision=None):
    path = safe_directory(project, workspace=True, model=cfg["modelDirectory"])
    manager = Path(cfg["modelDirectory"]).expanduser().resolve().parent / "manager"
    if path.is_relative_to(manager) or manager.is_relative_to(path):
        raise ValueError("Workspace and manager state directory must not overlap")
    args = base_run() + ["--rm", "--interactive",
            "--userns=keep-id:uid=1000,gid=1000", "--user=1000:1000",
            "--mount", f"type=bind,src={path},target=/work,bind-nonrecursive",
            "--workdir=/work", "--env=OPENAI_BASE_URL=http://strata:8080/v1",
            "--env=OPENAI_API_KEY=local-only"]
    if dev:
        args += ["--mount", f"type=bind,src={tools or tools_directory(cfg, path)},target=/tools,bind-nonrecursive"]
    if state:
        # Persistent agent home (chat history, config) of one workspace, never shared with others.
        args += ["--mount", f"type=bind,src={state},target=/state,bind-nonrecursive",
                 "--env=AIBOX_STATE_HOME=/state"]
    if context:
        args += [f"--env=AIBOX_CONTEXT={int(context)}"]
    if vision is not None:
        args += [f"--env=AIBOX_VISION={'1' if vision else '0'}"]
    if full_access:
        # Only changes the agent's own approval prompts inside the container; mounts and caps stay.
        args += ["--env=AIBOX_FULL_ACCESS=1"]
    if online:
        # Explicit opt-in: the same container additionally joins the NAT network, so package
        # downloads work. Still only PROJECT is mounted; the model API stays on the private net.
        args += ["--network", OUTBOUND]
    if sys.stdin.isatty() and sys.stdout.isatty():
        args += ["--tty"]
    # The shell is inside the container. No host command string is evaluated.
    bootstrap = '''umask 077
export HOME
if [ -n "${AIBOX_STATE_HOME:-}" ]; then
  HOME="$AIBOX_STATE_HOME"
else
  HOME="$(mktemp -d "${TMPDIR:-/tmp}/aibox-home.XXXXXXXX")"
fi
mkdir -p "$HOME/.config/opencode" "$HOME/.config/git"
cp /share/aibox/SKILLS.md "$HOME/.config/opencode/AGENTS.md"
printf '%s\n' node_modules/ dist/ .shots/ build/ .gradle/ __pycache__/ > "$HOME/.config/git/ignore"
export GIT_AUTHOR_NAME="${GIT_AUTHOR_NAME:-AI Box agent}" GIT_COMMITTER_NAME="${GIT_COMMITTER_NAME:-AI Box agent}"
export GIT_AUTHOR_EMAIL="${GIT_AUTHOR_EMAIL:-agent@aibox.invalid}" GIT_COMMITTER_EMAIL="${GIT_COMMITTER_EMAIL:-agent@aibox.invalid}"
python3 - <<'PY'
import json, os
ctx = int(os.environ.get("AIBOX_CONTEXT") or 16384)
vision = os.environ.get("AIBOX_VISION") == "1"
config = {
    "$schema": "https://opencode.ai/config.json",
    "autoupdate": False,
    "share": "disabled",
    "enabled_providers": ["local"],
    "model": "local/local",
    "provider": {"local": {
        "npm": "@ai-sdk/openai-compatible",
        "name": "Local (AI Box)",
        "options": {"baseURL": "http://strata:8080/v1", "apiKey": "local-only", "timeout": False},
        "models": {"local": {
            "name": "Local model", "attachment": vision, "tool_call": True, "reasoning": True,
            "limit": {"context": ctx, "output": min(16384, max(1024, ctx // 4))},
            "modalities": {"input": ["text", "image"] if vision else ["text"], "output": ["text"]}}}}},
}
if os.environ.get("AIBOX_FULL_ACCESS") == "1":
    # The container is the sandbox: no approval prompts inside it. external_directory is allowed
    # because OpenCode itself uses /tmp; the host is still reachable only through the mounts.
    config["permission"] = {"edit": "allow", "bash": "allow", "webfetch": "allow",
                            "doom_loop": "allow", "external_directory": "allow"}
path = os.path.join(os.environ["HOME"], ".config/opencode/opencode.json")
with open(path, "w") as stream:
    json.dump(config, stream, indent=2)
PY
exec "$@"
'''
    image = dev_image(cfg) if dev else os.environ["AIBOX_AGENT_IMAGE"]
    return args + [image, "/bin/bash", "-e", "-c", bootstrap, "aibox", *command]



WS_NAME = re.compile(r"^[a-z0-9][a-z0-9-]{0,39}$")
WS_TEMPLATES = {
    "plain": "",
    "web": "Web project. Node and Vite are available; build to dist/. Use `shot URL OUT.png` to look at pages.\n",
    "android": ("Android/Kotlin project. Use the project's ./gradlew; Gradle, JDKs and the Android command line tools "
                "live in /tools (ANDROID_HOME=/tools/android-sdk). Never accept Android SDK licences without asking the user.\n"),
    "nix": ("NixOS configuration project. The sandbox has no nix: edit files and check syntax by reading, "
            "but do not claim an evaluation or build passed. Keep the repository's conventions (see its AGENTS.md).\n"),
}


def ws_root(cfg):
    """Visible area for everything per workspace (chat homes, tools); default ~/projects/_aibox."""
    configured = cfg.get("workspaceRoot")
    root = Path(configured).expanduser() if configured else Path.home() / "projects" / "_aibox"
    root.mkdir(mode=0o700, parents=True, exist_ok=True)
    return safe_directory(root)


def ws_dir(cfg, name, *, must_exist=True):
    if not WS_NAME.match(name or ""):
        raise ValueError("Workspace names use a-z, 0-9 and '-', at most 40 characters")
    path = ws_root(cfg) / name
    if path.is_symlink():
        raise ValueError("Workspace directory must not be a symlink")
    if must_exist and not (path / "workspace.json").is_file():
        raise ValueError(f"Unknown workspace {name!r}; see aibox ws list")
    return path


def ws_load(cfg, name):
    data = json.loads((ws_dir(cfg, name) / "workspace.json").read_text())
    if data.get("name") != name:
        raise ValueError("Workspace metadata does not match its directory")
    return data


def ws_new(cfg, name, *, template="plain", path=None, tools_group=None, online=True, full_access=True):
    if template not in WS_TEMPLATES:
        raise ValueError(f"Unknown template {template!r}; choose from: {', '.join(WS_TEMPLATES)}")
    group = tools_group or name
    if not WS_NAME.match(group):
        raise ValueError("Tools group names use a-z, 0-9 and '-'")
    directory = ws_dir(cfg, name, must_exist=False)
    if directory.exists():
        raise ValueError(f"Workspace {name!r} already exists")
    project = Path(path).expanduser() if path else Path.home() / "projects" / name
    created = not project.exists()
    project.mkdir(parents=True, exist_ok=True)
    project = safe_directory(project, workspace=True, model=cfg["modelDirectory"])
    root = ws_root(cfg)
    if project.is_relative_to(root) or root.is_relative_to(project):
        raise ValueError("The project folder must not overlap the aibox workspace area")
    (directory / "home").mkdir(mode=0o700, parents=True)
    (root / "_tools" / group).mkdir(mode=0o700, parents=True, exist_ok=True)
    agents = project / "AGENTS.md"
    if WS_TEMPLATES[template] and not agents.exists():
        agents.write_text(f"# {name}\n\n{WS_TEMPLATES[template]}")
    meta = {"name": name, "template": template, "project": str(project), "toolsGroup": group,
            "online": online, "fullAccess": full_access, "created": int(time.time())}
    (directory / "workspace.json").write_text(json.dumps(meta, indent=2) + "\n")
    return meta, created


def ws_list(cfg):
    items = []
    for entry in sorted(ws_root(cfg).iterdir()):
        if entry.name.startswith("_") or not (entry / "workspace.json").is_file():
            continue
        try:
            items.append(ws_load(cfg, entry.name))
        except (ValueError, OSError, json.JSONDecodeError):
            items.append({"name": entry.name, "error": "unreadable metadata"})
    return items


def server_features():
    """Context size and vision support of the running inference server, for the agent's model limits."""
    data = owned_server()
    if not data or not data.get("State", {}).get("Running"):
        raise ValueError("Inference is not running. Start it first, for example: aibox ui --long-context lc256-iq3")
    cmd = data.get("Config", {}).get("Cmd") or []
    try:
        context = int(cmd[cmd.index("--ctx-size") + 1])
    except (ValueError, IndexError):
        context = 16384
    return context, "--mmproj" in cmd


def ws_agent_args(cfg, name, command, *, context=None, vision=None):
    meta = ws_load(cfg, name)
    root = ws_root(cfg)
    if not WS_NAME.match(str(meta.get("toolsGroup", ""))):
        raise ValueError("Invalid tools group in workspace metadata")
    tools = root / "_tools" / meta["toolsGroup"]
    tools.mkdir(mode=0o700, parents=True, exist_ok=True)
    # Only the home subfolder is mounted: the agent can never edit workspace.json (project path, settings).
    state = ws_dir(cfg, name) / "home"
    return agent_args(cfg, meta["project"], command, online=meta["online"], full_access=meta["fullAccess"],
                      dev=True, tools=tools.resolve(), state=state.resolve(),
                      context=context, vision=vision)


def ws_remove(cfg, name, *, with_project=False):
    meta = ws_load(cfg, name)
    directory = ws_dir(cfg, name)
    root = ws_root(cfg)
    if not directory.resolve().is_relative_to(root):
        raise ValueError("Refusing to delete outside the workspace area")
    shutil.rmtree(directory)
    group = meta["toolsGroup"]
    shared = any(item.get("toolsGroup") == group for item in ws_list(cfg))
    if not shared and (root / "_tools" / group).is_dir():
        shutil.rmtree(root / "_tools" / group)
    if with_project:
        project = Path(meta["project"]).resolve()
        if project == Path.home().resolve() or not project.is_relative_to(Path.home().resolve()):
            raise ValueError("Refusing to delete this project folder")
        shutil.rmtree(project)
    return meta, not shared


def main():
    parser = argparse.ArgumentParser(prog="aibox", description=__doc__)
    sub = parser.add_subparsers(dest="action", required=True)
    p = sub.add_parser("prepare", help="Load coding image and explicitly build HIP runtime, no models")
    p.add_argument("--agent-only", action="store_true")
    p.add_argument("--strata", action="store_true", help="Prepare legacy Strata instead of Prism llama.cpp")
    p.add_argument("--kvmem", action="store_true", help="Build the optional KVMem long-context runtime (separate image)")
    p.add_argument("--dev", action="store_true", help="Build the optional Debian dev coding image (needs internet)")
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
    p.add_argument("--profile", choices=("qwen27-iq4xs", "qwen27-iq3", "bonsai27-pq2"))
    p.add_argument("--text-only", action="store_true", help="Explicitly omit the vision projector")
    p.add_argument("--long-context", choices=("lc64", "lc128", "lc256", "lc512", "lc256-iq3", "lc256-bonsai"),
                   help="Optional KVMem mode (model pinned by preset); omitted = unchanged 16K Prism path")
    p.add_argument("--allow-experimental", action="store_true")
    p.add_argument("--port", type=int, default=8766)
    p.add_argument("--no-open", action="store_true", help="Print the address without launching a browser")
    p = sub.add_parser("start", help="Start a pinned model on the private network")
    p.add_argument("--strata", action="store_true")
    p.add_argument("--profile", choices=("qwen27-iq4xs", "qwen27-iq3", "bonsai27-pq2"))
    p.add_argument("--text-only", action="store_true")
    p.add_argument("--long-context", choices=("lc64", "lc128", "lc256", "lc512", "lc256-iq3", "lc256-bonsai"))
    p.add_argument("--allow-experimental", action="store_true")
    p = sub.add_parser("plan", help="Print the memory plan and checks for a long-context preset; starts nothing")
    p.add_argument("preset", choices=("lc64", "lc128", "lc256", "lc512", "lc256-iq3", "lc256-bonsai"))
    p.add_argument("--profile", choices=("qwen27-iq4xs", "qwen27-iq3"))
    p.add_argument("--text-only", action="store_true")
    for name in ("stop", "status", "logs"):
        sub.add_parser(name)
    wsp = sub.add_parser("ws", help="Named workspaces: own project, tools, chat history and sandbox settings")
    wsub = wsp.add_subparsers(dest="ws_action", required=True)
    q = wsub.add_parser("new", help="Create a workspace")
    q.add_argument("name")
    q.add_argument("--template", default="plain", choices=tuple(WS_TEMPLATES))
    q.add_argument("--path", help="Project folder (default ~/projects/NAME)")
    q.add_argument("--tools-group", help="Share the /tools folder with other workspaces of the same group")
    q.add_argument("--offline", action="store_true", help="No internet for this workspace")
    q.add_argument("--ask", action="store_true", help="Keep the agent's approval prompts")
    q = wsub.add_parser("list", help="List workspaces")
    q.add_argument("--json", action="store_true")
    for action, text in (("shell", "Open a shell in the workspace sandbox"), ("code", "Start OpenCode in the workspace sandbox")):
        q = wsub.add_parser(action, help=text)
        q.add_argument("name")
        q.add_argument("rest", nargs=argparse.REMAINDER, help="Extra arguments for opencode, for example: --continue")
    q = wsub.add_parser("rm", help="Delete a workspace: its chats and tools; the project folder only with --with-project")
    q.add_argument("name")
    q.add_argument("--with-project", action="store_true")
    q.add_argument("--yes", action="store_true")
    p = sub.add_parser("shell", help="Open offline coding shell sharing only PROJECT")
    p.add_argument("--online", action="store_true", help="Also allow outbound internet (package downloads) for this session")
    p.add_argument("--full-access", action="store_true", help="Agent runs without approval prompts; the container stays the only boundary")
    p.add_argument("--dev", action="store_true", help="Debian dev image with a persistent /tools folder; implies --online and --full-access")
    p.add_argument("project")
    p = sub.add_parser("exec", help="Run a command inside the offline coding container")
    p.add_argument("--online", action="store_true", help="Also allow outbound internet (package downloads) for this session")
    p.add_argument("--full-access", action="store_true", help="Agent runs without approval prompts; the container stays the only boundary")
    p.add_argument("project")
    p.add_argument("command", nargs=argparse.REMAINDER)
    args = parser.parse_args()
    if os.getuid() == 0:
        raise ValueError("Run aibox as your normal user, without sudo")
    cfg = load_config()
    if args.action == "prepare":
        if args.dev:
            prepare_dev(cfg)
        elif args.kvmem:
            prepare_kvmem(cfg)
        else:
            prepare(cfg, args.agent_only) if args.agent_only or args.strata else prepare_llama(cfg)
    elif args.action == "plan":
        name, _ = profile(cfg, longcontext_profile(cfg, args.preset, args.profile))
        settings = longcontext_settings(cfg, args.preset, allow_experimental=True)
        plan, problems = longcontext_plan(cfg, name, settings, vision=not args.text_only)
        print(json.dumps({**plan, "problems": problems, "server_args": kvmem_server_args(cfg, name, settings, vision=not args.text_only)}, indent=2))
        return 1 if problems else 0
    elif args.action == "prepare-ui":
        prepare_ui(cfg)
    elif args.action == "models":
        print(json.dumps({"selected": profile(cfg)[0], "context": cfg.get("contextSize", 16384),
                          "kv_k": "q8_0", "kv_v": "q8_0", "mtp_max": 2, "profiles": profiles(),
                          "long_context_presets": longcontext_presets()}, indent=2))
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
            start_llama(cfg, args.profile, vision=not args.text_only, long_context=args.long_context,
                        allow_experimental=args.allow_experimental)
    elif args.action == "ui":
        if args.strata:
            ui(cfg, port=args.port, no_open=args.no_open)
        else:
            start_llama(cfg, args.profile, port=args.port, no_open=args.no_open, vision=not args.text_only,
                        long_context=args.long_context, allow_experimental=args.allow_experimental)
    elif args.action == "ws":
        if args.ws_action == "new":
            meta, created = ws_new(cfg, args.name, template=args.template, path=args.path, tools_group=args.tools_group,
                                   online=not args.offline, full_access=not args.ask)
            print(f"Workspace {args.name} created. Project: {meta['project']}{' (new folder)' if created else ''}")
            print(f"Image missing? aibox prepare --dev   |   Start: aibox ws code {args.name}")
        elif args.ws_action == "list":
            items = ws_list(cfg)
            if args.json:
                print(json.dumps(items, indent=2))
            else:
                for item in items:
                    print(f"{item['name']:<20} {item.get('template', '?'):<8} {item.get('project', item.get('error'))}")
        elif args.ws_action == "rm":
            meta = ws_load(cfg, args.name)
            if not args.yes:
                raise ValueError(f"This deletes the chats and tools of {args.name!r}"
                                 f"{' AND the project folder ' + meta['project'] if args.with_project else ''}. Repeat with --yes")
            ws_remove(cfg, args.name, with_project=args.with_project)
            print(f"Workspace {args.name} removed." + ("" if args.with_project else f" Project folder kept: {meta['project']}"))
        else:
            ensure_image(dev_image(cfg))
            ensure_network()
            ensure_outbound_network() if ws_load(cfg, args.name)["online"] else None
            rest = args.rest[1:] if args.rest and args.rest[0] == "--" else args.rest
            command = ["/bin/bash"] if args.ws_action == "shell" else ["opencode", *rest]
            features = server_features() if args.ws_action == "code" else (None, None)
            return run(*ws_agent_args(cfg, args.name, command, context=features[0], vision=features[1]),
                       check=False).returncode
    elif args.action in ("shell", "exec"):
        dev = args.dev
        online, full_access = args.online or dev, args.full_access or dev
        ensure_image(dev_image(cfg) if dev else os.environ["AIBOX_AGENT_IMAGE"])
        ensure_network()
        if online:
            ensure_outbound_network()
            shared = "the project folder and the persistent /tools folder are" if dev else "only the project folder is"
            print(f"ONLINE: this container can reach the internet; {shared} shared.", file=sys.stderr)
        command = ["/bin/bash"] if args.action == "shell" else args.command
        if command and command[0] == "--":
            command = command[1:]
        if not command:
            raise ValueError("Expected a command after PROJECT")
        result = run(*agent_args(cfg, args.project, command, online=online, full_access=full_access, dev=dev), check=False)
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
                          "kvmem_image_prepared": exists("image", kvmem_image(cfg)),
                          "engine": (data or {}).get("Config", {}).get("Labels", {}).get(f"{LABEL}.engine"),
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
