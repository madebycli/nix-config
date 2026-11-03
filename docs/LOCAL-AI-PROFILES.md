# Selected coding profiles: IQ4_XS / Bonsai PQ2_0 + Q8 KV + MTP depth 2

The default `aibox prepare`, `doctor`, `start` and `ui` now use a pinned
**Prism ML fork of llama.cpp**, compiled for HIP `gfx1030` (RX 6800), rather
than Strata. Ollama is not used. Existing Strata images/models are retained;
legacy commands require `--strata`. Nothing starts or downloads on Nix activation.

## NixOS configuration

```nix
my.features.local-ai.enable = true;
my.features.local-ai.defaultProfile = "qwen27-iq4xs";
my.features.local-ai.contextSize = 16384;
```

In your existing checkout, use `nx pull`, `nixctl on local-ai` and `nx switch`.
If you set a default profile/context in Nix, do so before the switch.

Keep the enable switch as one line in the host's `features.nix` for nixctl.
The feature remains disabled in the committed host defaults. Changing the
context/profile does not recompile the HIP engine. Rebuild your actual host
configuration, log in again if render/video groups changed, then run as your
normal user, without sudo:

```bash
aibox prepare                  # engine/UI + coding image, no model weights
aibox doctor                   # actual HIP device enumeration
aibox models                   # pinned sources, sizes, hashes and settings
aibox fetch bonsai27-pq2        # explicit ~8.29 GB model + projector download
aibox ui --profile bonsai27-pq2 # load model and open http://127.0.0.1:8766
```

For the selected Qwen IQ4_XS alternative:

```bash
aibox stop
aibox fetch qwen27-iq4xs        # explicit ~16.40 GB model + projector download
aibox ui --profile qwen27-iq4xs
```

`fetch` verifies SHA256 before accepting files, resumes `.part` downloads and
never substitutes another quantization. A corrupt existing file is rejected;
remove that specific file and retry. `verify PROFILE` rechecks both artifacts.
Artifacts are pinned to immutable Hugging Face revisions in
`pkgs/aibox/profiles.json`, not floating `main` download URLs.

## What both profiles request

| Setting | Value |
|---|---|
| Context per slot | explicitly 16384 by default, configurable in Nix |
| Parallel slots | 1 |
| Target KV K / V | q8_0 / q8_0 |
| Draft KV K / V | q8_0 / q8_0 |
| Speculation | native bundled `draft-mtp` |
| Maximum proposed tokens per draft | 2 |
| GPU target / draft | ROCm0 / ROCm0, all weight layers requested |
| Automatic memory fitting | off |
| Model loading | `--load-mode none`, no mmap/expert SSD backend |
| Vision | matching projector included by default |

IQ4_XS describes **Qwen weight** quantization. Q8_0 here primarily describes
**KV cache** quantization, not a switch of the entire model to 8-bit. Qwen's
embedded MTP matrices are Q4_0; Bonsai's MTP matrices are Q8_0. Recurrent hybrid
attention state and compute buffers are additional allocations, not all Q8 KV.

MTP depth 2 means **up to two proposals, each verified by the target model**.
It neither guarantees two accepted tokens nor a speedup. The pinned server is
patched to reject a requested but uninitialized MTP implementation, and the
controller requires the actual MTP initialization log after health succeeds.
Health plus initialization is not evidence of nonzero acceptance or correct
vision behavior; those require real inference tests on the target GPU.

## Provenance and compatibility

- `qwen27-iq4xs`: bartowski/Qwen3.8-27B-GGUF IQ4_XS with embedded MTP head,
  matching f16 projector. The file is 15,475,951,328 bytes (~14.41 GiB).
- `bonsai27-pq2`: **ProCreations community r3-mtp bundle**, not an official Prism
  release. It keeps the original Bonsai PQ2_0 target tensors and adds a trained
  Q8_0 MTP head. The combined file is 7,657,489,728 bytes (~7.13 GiB). It uses
  Prism ML's separate Q8_0 projector (629,246,976 bytes).
- The official plain Bonsai files have no MTP head. They are deliberately not
  substituted for this MTP-required profile. PQ2_0 needs Prism's Hadamard-aware
  runtime; do not replace it with an arbitrary stock llama.cpp binary.
- Runtime source is pinned to Prism `a15369706017f177cae8aa40b6b8592259a48806`
  (`prism-b10828-a153697`). That source contains the Bonsai MTP embedding inverse
  Hadamard path. RX 6800 GPU correctness and throughput are still acceptance
  requirements, not inferred from builds or NVIDIA measurements.

Primary sources:
[Qwen quantization and embedded MTP](https://huggingface.co/bartowski/Qwen3.8-27B-GGUF),
[Bonsai MTP bundle and limitations](https://huggingface.co/ProCreations/Ternary-Bonsai-2-27B-MTP),
[official Bonsai/projector](https://huggingface.co/prism-ml/Ternary-Bonsai-2-27B-gguf),
[pinned runtime](https://github.com/PrismML-Eng/llama.cpp/tree/a15369706017f177cae8aa40b6b8592259a48806).

## RX 6800 memory and acceptance

**Qwen IQ4_XS is a tight fit, not a promise of full GPU residency.** Its weights,
~0.86 GiB projector, KV, recurrent state, draft/compute buffers and the running
desktop must all fit in 16 GiB. An allocation failure is expected to be possible
with the selected settings. The controller does not silently reduce context,
change cache types, turn MTP off or offload weight layers to CPU. Bonsai has much
more space left for these allocations and should be the first hardware test.

An explicit `--text-only` on `start`/`ui` omits the projector and gives up image
input; it does not change MTP, quantization or context. Model weights are read
from disk on load and checked on each start. No SSD expert paging is configured;
the operating system's own swap policy is separate and is not disabled here.

```bash
aibox status
aibox logs
# The UI should produce a complete answer and report actual generation timing.
# Also submit a real screenshot and check its factual description.
aibox stop
```

Measure MTP proposal/acceptance statistics from real generation logs, decode
speed and prompt time with representative coding prompts. Do not call an
initialized draft engine a measured speedup. Multimodal input plus MTP needs its
own correctness check; the upstream speculative path has vision-related TODOs.
No automatic MTP-off fallback is supplied for image requests.

## Isolation, private API and coding tools

Inference receives only the selected profile directory read-only, `/dev/kfd`
and the configured render node. The coding container receives only PROJECT
read-write, with no home, model files, engine socket or GPU devices. Both share
the internal network. No cloud credentials or host files are added.

```bash
aibox stop
aibox start --profile bonsai27-pq2   # API only, no host port
aibox exec ~/projects/ki -- curl --fail http://strata:8080/health
aibox shell ~/projects/ki
```

The internal hostname remains `strata` for compatibility, even though the
selected process is llama-server. `ui` additionally publishes only
`127.0.0.1:8766`; it is llama.cpp's **chat UI**, not Strata's model manager.
Stop a running service before switching between private and UI modes. Models
are selected by the profile command, not downloaded by this chat UI.

The existing coding image still contains Codex and the previously configured
tools. A full browser/screenshot/build agent loop is separate work; adding the
vision projector alone does not implement that workflow.

## Legacy Strata

```bash
aibox prepare --strata
aibox doctor --strata
aibox prepare-ui
aibox ui --strata
# or legacy private server.json inference:
aibox start --strata
# mock API without any model:
aibox smoke
```

Stop the current server before these mode changes. See [legacy setup and
isolation](LOCAL-AI.md). Old models and manager state are not deleted.
