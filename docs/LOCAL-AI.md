# Local AI containers, without bundled models

Optional NixOS infrastructure for nyx (RX 6800, gfx1030). Both hosts keep
`my.features.local-ai.enable = false;` by default. The existing Ollama `ai`
feature and MicroVM `agentbox` remain separate. Neither model selection nor a
model download is performed by NixOS activation, boot, CI or `aibox prepare`.

## Enable and prepare

From your normal user, in your existing checkout:

```bash
nx pull
nixctl on local-ai
nx switch
```

Log out and back in after adding render/video group membership. Then:

```bash
aibox prepare          # explicitly builds HIP runtime and imports coding image
aibox doctor           # actual GPU enumeration, no model required
aibox status
mkdir -p ~/projects/ai-test
aibox shell ~/projects/ai-test
```

Preparation downloads ROCm/compiler/runtime dependencies and Strata source,
then compiles the engine, but **no model weights**. Allow substantial disk
space and build time for the ROCm development image. `buildJobs` defaults to
2 to bound compile-time RAM; inference has no CPU quota or RAM cap.
The first build can take tens of minutes. The CLI never silently pulls a
runtime image when starting inference or opening a workspace.

The shell already contains Codex, Git, Python, Node.js, GCC, Make, curl, jq,
ripgrep and a planning/testing workflow in `$HOME/.codex/AGENTS.md`.
Its writable home is temporary; project changes persist. Nothing is installed
into the project automatically. Codex is configured for Strata's Responses API;
real model-specific tool loops still require acceptance with the eventual model.
`aibox shell` alone does not start inference or make Codex functional without a model.

## Model-free tests

```bash
aibox smoke             # real API with mock answers, not an AI model
aibox exec ~/projects/ai-test -- curl --fail http://strata:8080/health
aibox exec ~/projects/ai-test -- curl --fail http://strata:8080/v1/models
aibox logs
aibox stop
```

`doctor` passes only `/dev/kfd` and the configured render node to the model
image, with networking disabled and no bind mounts. It is a hardware test to
run on nyx, not proof of model quality or inference throughput. RX 6800 support
in upstream Strata is community-reported; do not interpret a successful build
as a successful GPU run.

## Architecture and isolation

- Rootless Podman runs as your normal user, never with sudo or a Docker group.
  The CLI refuses root. No privileged service or container API socket is enabled.
- Inference receives GPU devices and, later, a dedicated model folder read-only.
  It receives no workspace, home, host store, SSH agent or graphical sockets.
- Coding receives **one explicitly selected, user-owned project directory** as
  `/work`. Root/home/system paths and overlap with models are rejected. Nested
  host mounts are excluded. No GPU devices, host credentials, runtime sockets or
  full host `/nix/store` are bound. The image contains its own Nix tool closure.
- Both runtimes have read-only roots, dropped capabilities, no new privileges,
  private PID/IPC namespaces and the default seccomp policy. No unconfined
  seccomp, host network, host IPC, memory locking bypass or device cgroup bypass.
- An internal, labelled container network connects coding to `strata:8080`.
  No host/LAN port is published. The controller verifies an existing network's
  internal policy. Proxy variables from the host are not inherited.
- This initial profile is **offline**. Internet package installation and cloud
  Claude/Codex providers do not work inside it. No implicit online mode is added.
  Add dependencies declaratively through `agentExtraPackages` and rebuild.
- Container isolation shares the host kernel and GPU driver. It is not an
  absolute boundary against kernel/driver exploits. Unlike the stronger
  dedicated-account proposal in the plan, this first implementation uses your
  normal rootless account; a container escape could reach that account's files.
  Files already inside the selected project are available to the agent.

There is no autostart, no published API, no CPU quota and no arbitrary RAM limit.
Heavy inference can still compete with the desktop for RAM and GPU resources;
`aibox stop` stops inference and releases its resources. No model or project is
deleted by stop. Project compiler caches can be placed inside the project.

## Nix options and updates

```nix
my.features.local-ai.enable = true;
my.features.local-ai.gpuArch = "gfx1030";
my.features.local-ai.renderDevice = "/dev/dri/renderD128";
my.features.local-ai.modelDirectory = "/home/USERNAME/.local/share/nx-ai/models";
my.features.local-ai.buildJobs = 2;
my.features.local-ai.agentExtraPackages = [ pkgs.cmake pkgs.ninja ];
```

Check the actual render node on multi-GPU hosts. The other host is not assumed
to have an RX 6800. Nix pins the coding tools through the existing flake lock.
The Strata source commit is fixed in `pkgs/aibox/Containerfile`; upstream CMake
also pins llama.cpp. Its Python runtime requirements are pinned upstream.
ROCm's default `7.2.3-complete` tag and Ubuntu apt repositories can change;
this runtime is not a fully reproducible Nix derivation. Supply a verified
registry digest using `hipBaseImage` for a stricter base-image pin.

After changing tools, `nx switch` rebuilds the coding image. `aibox prepare`
imports it and builds the matching inference image when necessary. Runtime
tags incorporate their build inputs, so a changed configuration requires
preparation instead of silently using an old tag. Stop before changing a
running server. Old OCI build caches are Podman-managed; nothing automatically
prunes user images or Nix generations.

## Supplying a model later

No `server.json` or model directory is created automatically. When a model
has been selected and prepared, place its files in `modelDirectory` and add a
`server.json` with only `args`, `tokenizer` and `model_name`. All paths must
refer to their **container** locations under `/models`, not host paths.
Tokenizer must be under `/models`. Example shape, not a ready-made model pack:

```json
{
  "model_name": "local",
  "tokenizer": "/models/MODEL/tokenizer",
  "args": ["--serve", "--pack", "/models/MODEL/pack", "--native", "/models/MODEL/weights.gguf", "--max-context", "16384"]
}
```

Actual arguments differ between Gyro and conventional GGUF packs. The model
needs its own tokenizer, metadata, PLE/expert files and optional MTP artifacts;
renaming a GGUF or using a random pack is insufficient. Prepare that separately
when the model is chosen. The controller does not download, convert or guess it.
`aibox start` refuses missing configuration; `aibox logs` shows engine errors.
The runtime fixes the executable, working directory and HIP backend, and refuses
extra server settings such as MCP, file tools or image generation. Reasoning
and tool-call quality remain model/client-dependent. No Claude compatibility
promise follows merely from API routes existing.

## Verification

`python3 tests/aibox_test.py` covers argument boundaries, forbidden host mounts,
root refusal, internal-network validation, model-free behavior and workspace
selection. The dedicated Local AI workflow is configured to build the actual HIP
engine for gfx1030 without a GPU, exercise the real API's mock mode and check a
real rootless coding container. A workflow file alone is not evidence of a
successful run. These checks do not replace nyx `aibox doctor`,
real inference, memory-pressure measurement or complete client tool-loop tests.
