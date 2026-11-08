> Default commands now serve the selected IQ4_XS/Bonsai profiles through Prism
> llama.cpp. Start with [current profile setup](LOCAL-AI-PROFILES.md). This page
> documents the retained **legacy Strata** path and shared isolation boundaries.

# Local AI containers, without bundled models

Optional NixOS infrastructure for nyx (RX 6800, gfx1030). Both hosts keep
`my.features.local-ai.enable = false;` by default. The existing Ollama `ai`
feature and MicroVM `agentbox` remain separate. Neither model selection nor a
model download is performed by NixOS activation, boot, CI or `aibox prepare --strata`.

## Enable and prepare

From your normal user, in your existing checkout:

```bash
nx pull
nixctl on local-ai
nx switch
```

Log out and back in after adding render/video group membership. Then:

```bash
aibox prepare --strata          # explicitly builds HIP runtime and imports coding image
aibox doctor --strata           # actual GPU enumeration, no model required
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

The shell already contains Git, Python, Node.js, GCC, Make, curl, jq,
ripgrep and a planning/testing workflow in `$HOME/.config/opencode/AGENTS.md`. The coding agent (OpenCode) lives in the dev image (`aibox prepare --dev`).
Its writable home is a private mode-0700 directory created by the container user
inside the existing `/tmp` tmpfs; it is temporary and project changes persist.
No Docker-specific `uid=`/`gid=` tmpfs options are needed. Nothing is installed
into the project automatically. OpenCode is configured for the local OpenAI-compatible API;
real model-specific tool loops still require acceptance with the eventual model.
`aibox shell` alone does not start inference or make the agent functional without a model.

## Full Strata model manager

The full upstream React app and Node host include Strata Control: model catalog,
explicit downloads/repair/removal, load/unload, settings, monitoring and chat.
This is the full `apps/host` application, not `serve/web`'s chat-only UI.

After `nx pull` and `nx switch`, using your already prepared HIP runtime:

```bash
aibox stop
aibox prepare-ui        # build full app layer; no HIP recompile or model weights
aibox ui --strata                # opens http://127.0.0.1:8766
```

`prepare-ui` reuses the existing engine image and builds the pinned app's frontend
with Node 24.19.0 and its npm lockfile. It downloads web/build dependencies, not
model weights. If the underlying runtime is missing, run `aibox prepare --strata` first.
`ui` never implicitly builds or pulls images. The original runtime image identity
is unchanged by this addition, so its successful HIP build stays reusable.

Open **Models** to choose a supported model and explicitly download it. Load it
when ready, adjust its settings and use chat. No `server.json` is needed for this
workflow. Opening the manager itself neither selects nor loads a model; the
upstream app may read hardware/state or check component updates. A model download
job can also update the engine through upstream's component updater. Strata
Control uses the existing local gfx1030 engine as an unsigned local component;
its ROCm libraries stay in the parent image. It is not a standalone upstream
engine release. The existing image does not contain a vision-reader executable.

The configured `modelDirectory` is writable **only for the manager**; upstream
may keep weights under its `models/` subdirectory. App settings, generated run
configs, components and the app's private workspace persist in a sibling
`manager/` directory. `aibox stop` preserves all of these. Select `/models` inside
the UI for the mounted model storage, not your host's `/home/...` path. Arbitrary
host folders are unavailable. The app's own workspace lives under `/state`; use
`aibox shell PROJECT` for your explicitly shared coding project.

Only **127.0.0.1:8766** is published. The manager also joins a separate outbound
container network for explicit downloads and optional online app features. The
coding container remains attached only to the internal network. The manager has
GPU access, its model folder and its own state, with no host home/store/socket
mount. Its management API is reachable by the coding container on the private
network, so treat those containers as one trust domain for model management.

```bash
aibox ui --strata --no-open       # print the address without launching the browser
aibox ui --strata --port 8767     # another unprivileged local port
aibox status
aibox logs
aibox stop              # stop manager and its inference children
```

The command waits for the full host's `/api/health` endpoint. It refuses to
replace a running private `start`/`smoke` server; stop that first. Browser closure
does not stop the manager. The API remains `http://strata:8080/v1` inside aibox.
For legacy Strata, use the loaded model's exact API model ID or give
it the alias `local` in Strata. If you enable an API key in Strata, clients must
supply that key themselves; the wrapper does not read your saved app secrets.
End-to-end coding/tool loops require acceptance with the actual chosen model.

## Private manual server

`aibox start --strata` continues to use read-only models and a manually supplied
`server.json`, without any host-published port. `aibox smoke` is still a mock API
connectivity test; its `loaded: true` response does not mean weights are loaded.

## Model-free tests

If preparation stopped at `find_package(hip)` with `hipConfig.cmake` not found,
update the configuration and rebuild before retrying `aibox prepare --strata`. The
Containerfile explicitly supplies `/opt/rocm` as `CMAKE_PREFIX_PATH`, so CMake
can find the SDK's HIP/BLAS package metadata as well as its compiler. Existing
Podman images/caches do not need to be deleted. This corrects package discovery;
it is not proof that subsequent compilation or GPU inference succeeds.

If `aibox exec` or `shell` failed with `unknown mount option "uid=1000"`,
update with `nx pull` and `nx switch`. The controller now creates its private
temporary home inside `/tmp` instead of requesting an unsupported tmpfs owner
option. The images and Strata engine are unchanged, so `aibox prepare --strata` is not
required solely for this controller fix.

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
- The private `start` server receives GPU devices and a dedicated model folder read-only.
  The explicit full manager gets writable model/state folders as described above.
  It receives no workspace, home, host store, SSH agent or graphical sockets.
- Coding receives **one explicitly selected, user-owned project directory** as
  `/work`. Root/home/system paths and overlap with models or manager state are rejected. Nested
  host mounts are excluded. No GPU devices, host credentials, runtime sockets or
  full host `/nix/store` are bound. The image contains its own Nix tool closure.
- Both runtimes have read-only roots, dropped capabilities, no new privileges,
  private PID/IPC namespaces and the default seccomp policy. No unconfined
  seccomp, host network, host IPC, memory locking bypass or device cgroup bypass.
- An internal, labelled container network connects coding to `strata:8080`.
  No host port is published in the default CLI profile. Explicit `aibox ui --strata`
  publishes the UI/API on 127.0.0.1 only; no LAN port is published. The controller verifies an existing network's
  internal policy. Proxy variables from the host are not inherited.
- The coding profile is **offline by default**; `aibox shell --online DIR` / `aibox exec --online DIR -- CMD` additionally joins
  the labelled NAT network for that one session (no allow-list; only DIR is still shared). Otherwise internet package installation and cloud
  cloud providers do not work directly inside it. The manager has outbound
  access, and its upstream integrations can access the internet.
  Add dependencies declaratively through `agentExtraPackages` and rebuild.
- Container isolation shares the host kernel and GPU driver. It is not an
  absolute boundary against kernel/driver exploits. Unlike the stronger
  dedicated-account proposal in the plan, this first implementation uses your
  normal rootless account; a container escape could reach that account's files.
  Files already inside the selected project are available to the agent.

There is no autostart, no LAN-published API, no CPU quota and no arbitrary RAM limit.
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

After changing tools, `nx switch` rebuilds the coding image. `aibox prepare --strata`
imports it and builds the matching inference image when necessary. Runtime
tags incorporate their build inputs, so a changed configuration requires
preparation instead of silently using an old tag. Stop before changing a
running server. Old OCI build caches are Podman-managed; nothing automatically
prunes user images or Nix generations.

## Supplying a model later

For the private manual `aibox start --strata` path, no `server.json` is created automatically.
The full manager creates its storage directory on explicit startup. When a model
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
`aibox start --strata` refuses missing configuration; `aibox logs` shows engine errors.
The runtime fixes the executable, working directory and HIP backend, and refuses
extra server settings such as MCP, file tools or image generation. Reasoning
and tool-call quality remain model/client-dependent. No Claude compatibility
promise follows merely from API routes existing.

## Verification

`python3 tests/aibox_test.py` covers argument boundaries, forbidden host mounts,
root refusal, internal-network validation, model-free behavior and workspace
selection. `python3 tests/aibox_ui_test.py` checks full-manager lifecycle, loopback
publication and persistent-folder boundaries. The dedicated Local AI workflow is
configured to build the full app layer and probe its real Control/catalog endpoints
without downloading weights, build the actual HIP
engine for gfx1030 without a GPU, exercise the real API's mock mode and check a
real rootless coding container. A workflow file alone is not evidence of a
successful run. These checks do not replace nyx `aibox doctor --strata`,
real inference, memory-pressure measurement or complete client tool-loop tests.

## Full access, tools and online mode for the coding agent

```bash
aibox shell --online --full-access ~/projects/NAME
opencode       # inside the container (dev image)
```

- `--online` adds outbound internet for that session. `--full-access` only switches off the agent's own
  approval prompts and its nested sandbox (which cannot start inside the container). The container
  remains the boundary: one mounted project folder, read-only root, no capabilities, no GPU.
- `my.features.local-ai.agentToolsets` (default `web`, `jvm`) bakes Chromium plus `shot URL OUT.png`,
  JDK 21, Gradle, Kotlin and Maven into the image. Generic downloaded binaries (Playwright browsers,
  Android build tools) do not run on this Nix-built image, so tools are provided declaratively.
  After `nx switch` run `aibox prepare --agent-only`. The Android SDK is not included yet.

### Dev mode: the agent fetches the tool versions a project needs

```bash
aibox prepare --dev                       # once: builds a Debian dev image (internet; OpenCode 1.19.5 pinned)
aibox shell --dev ~/projects/NAME         # = --online --full-access, Debian image, persistent /tools
opencode
```

- `/tools` is `~/.local/share/nx-ai/agent-tools` (0700, separate from the project and models). Gradle
  distributions, JDKs, Node versions, Android command line tools and caches go there and survive the session.
  Environment variables point Gradle/Maven/npm/pip/mise/cargo caches into it.
- The image is ordinary Debian, so downloaded standard Linux binaries run. It contains JDK 17, Node 22, Python,
  build tools, Chromium and `shot URL OUT.png`. Projects needing other versions pull them into `/tools`.
- No root: `apt` is unavailable at runtime. A missing system library is added to `DevContainerfile`.
- Boundary unchanged: read-only root, no capabilities, no GPU, only PROJECT and `/tools` mounted,
  and no allow-list for the internet. The agent is told never to accept third-party licences (Android SDK)
  without asking. Unverified on nyx: OpenCode against the KVMem server, Gradle/Android builds.

### Workspaces: one sandbox profile per project

```bash
aibox prepare --dev                                   # once
aibox ws new chat-app --template android              # own project folder, tools and chat history
aibox ws new nixos --template nix --path ~/nix-config
aibox ws list
aibox ws code chat-app                                # start OpenCode there (needs the server running)
aibox ws code chat-app -- --continue                  # continue the last chat of that workspace
aibox ws shell nixos
aibox ws rm chat-app --yes                            # removes chats and tools, keeps the project folder
aibox ws rm chat-app --yes --with-project             # also deletes the project folder
```

Each workspace has its own project folder (default `~/projects/NAME`), its own `/tools` (so different
Gradle/JDK versions do not mix; `--tools-group NAME` shares one deliberately, e.g. one Android SDK), and
its own persistent agent home (`/state`) that keeps the OpenCode chat history. The container sees only those
three folders. `workspace.json` is not mounted, so the agent cannot change its own mounts or settings.
Defaults: internet on and agent approvals off inside the container (`--offline`, `--ask` change that).
The nix template cannot evaluate or build: there is no nix inside the sandbox. A browser UI for
managing workspaces is not implemented.

**Where things live.** Per-workspace data that the agent fetches or creates (downloaded tools, Gradle/JDK
versions, SDKs, caches, chat history) is stored visibly in `~/projects/_aibox/` (`my.features.local-ai.workspaceRoot`),
next to the project folders. The AI Box itself is not stored there: models stay in
`~/.local/share/nx-ai/models`, and container images in Podman's own storage.

### Local server connection (default)

The agent config is written at every start into the workspace's persistent home
(`~/.config/opencode/opencode.json`): provider `local` = `http://strata:8080/v1`, model `local/local`,
`enabled_providers = ["local"]` (no other provider can be selected), autoupdate and sharing off, request
timeout off (long prompts take minutes). Context size and image support are read from the running server,
so a 256K KVMem server and a 16K Prism server both get correct limits. `aibox ws code NAME` refuses to start
when no server is running. The first start downloads the `@ai-sdk/openai-compatible` provider package into
`/tools/cache`, so it needs internet once. With `--full-access` (default in workspaces) edit, bash and web
fetch are allowed without prompts. Access outside `/work` is also allowed, because OpenCode uses `/tmp`; inside the
container that reaches only its own read-only image, `/tmp`, `/tools` and `/state`, never the host beyond the mounts.
