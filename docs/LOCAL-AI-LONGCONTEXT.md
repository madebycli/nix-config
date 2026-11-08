# Optional long-context mode (KVMem) for Qwen3.8-27B IQ4_XS

**Status: implemented and unit-tested; UNVERIFIED on hardware.** No RX 6800 was
available when this was written. Every GPU, speed, VRAM, vision, MTP and quality
statement below is a plan or a source-based expectation, not a measurement.

The default 16K Prism path is unchanged and is the rollback. The long-context mode is a
separate image, a separate runtime and is only used when `--long-context` is given.

## What it is

[KVMem](https://github.com/kvmem/kvmem) keeps the complete KV history in host RAM and
retrieves relevant blocks into a bounded VRAM window per request. `-c` becomes the
*logical* workspace. Attention runs only over the window, **not over all 256K tokens**:
quality at long range depends on retrieval, so the probe below must be run.

Only `kvmem/kvmem` is used (pinned, see below). `RyensX/kvmem-kvarn-llama.cpp` was
reviewed and not used: it is a stale CUDA-only copy (v0.16, 2026-09-23) of
`kvmem/kvmem-llama.cpp`, which is itself superseded by `kvmem/kvmem`. A static scan
found no downloaders, obfuscation or binaries (not a full audit); it offers nothing
`kvmem/kvmem` lacks (no ROCm).

## Pins (reproducible)

| Item | Pin |
|---|---|
| KVMem | `kvmem/kvmem` `deb8e76582892a3f6f61bae0b728701b3b41cce7` (0.19.0) |
| llama.cpp base | `ggml-org/llama.cpp` `cd959bae99ff4bed22bef2604f45241c09bbb8c8` |
| Patch series | five ordered patches; `prepare-backends.py --check` verifies tree hashes (final `1a8155219356073fe1f8a3528d2c7f203521554b`). Reproduced here: every intermediate tree hash matched. |
| Model + projector | unchanged: `qwen27-iq4xs` in `profiles.json` (bartowski, sha256-pinned) |
| ROCm / HIP | `hipBaseImage` (7.2.3), target `gfx1030` |

This is **upstream llama.cpp + KVMem, not the Prism fork**. Prism is only needed for
Bonsai PQ2_0, so the mode is restricted to `qwen27-iq4xs` (Bonsai is rejected).

## Compatibility

| Item | Finding |
|---|---|
| Qwen3.8-27B IQ4_XS | Supported family; KVMem's reference recipe is IQ4_XS+MTP (RTX 5060 Ti, Q5 KV). Not tested with *this* bartowski file. |
| RX 6800 / gfx1030 / HIP | `gfx1030` is a documented build target and an RDNA2 FA fix is in the patch series, but KVMem's recorded ROCm long-context tests are RDNA4 (RX 9060 XT) / 7900 XTX. **No gfx1030 qualification exists.** RDNA2 + **F16 draft KV is a known gap**, so draft KV is quantized here. |
| Prism integration | Not combined: separate engine and image. Prism stays for 16K and Bonsai. |
| Vision | KVMem on ROCm runs the projector on CPU (`--no-mmproj-offload`); this saves ~0.86 GiB VRAM but image encoding is slower. The f16 projector with this server is untested. |
| MTP | `draft-mtp`, max 2, ReplaySSM (`--kvmem-mtp-state replay`). The controller checks `/slots` and stops the server if the speculative sampler is not active. Acceptance with KVMem retrieval is unmeasured. |
| Q8 KV | Requested type, default. `kvDtype = "q5_0"` is an explicit opt-in (KVMem's IQ4 recipe). |
| Streaming / tools | KVMem server provides OpenAI chat/responses with streaming and tools (jinja); Codex uses `responses`. The probe checks a tool call; coding-agent loops are unverified. |
| Templates | `--jinja` with the GGUF template; unverified against KVMem's own Qwen template handling. |

## The real bottleneck

IQ4_XS weights are 14.41 GiB of ~16 GiB. KV for Qwen3.8's 16 full-attention layers is
~34 KiB/token at q8_0 (assumed, ~23 KiB at q5_0), so VRAM leaves room for only a
**~16K-token working pool** (preset: 12288 history + 4096 generation), the same pool
as the current 16K profile. The three reference points:

- KVMem's IQ4 recipe on a headless 16 GiB RTX 5060 Ti: 32K + 12K pool, Q5 KV,
  CPU vision, peak 15.7 GiB with only 365 MiB free. A desktop session on the RX 6800
  will not leave that much.
- Full attention beyond ~40K tokens cannot be on the GPU with these weights at any KV
  type. Streaming KV over PCIe or attending on CPU is bandwidth-bound (estimate: single
  digit tokens/s at 128K+), which is why selective retrieval is the only option near
  your 48 t/s.
- A larger window needs VRAM: run the desktop on the Ryzen iGPU, use `kvDtype = "q5_0"`
  or (needs your approval, **not done**) a smaller weight quantization.

So 128K/256K are reachable as *logical* context. How good retrieval is with a 16K
window (the paper's near-lossless result used a 32K window) and how fast it is are exactly
what the tests on nyx must answer. Expected, not measured: decode below 48 t/s, slow
cold prefill (KVMem reports ~250 t/s overall on a 5060 Ti).

## Presets (all test configurations)

| Preset | Logical ctx | VRAM pool | Host KV quota | Container RAM cap |
|---|---:|---|---:|---:|
| `lc64` | 65,536 | 12288 + 4096 | 4 GiB | 12 GiB |
| `lc128` | 131,072 | 12288 + 4096 | 6 GiB | 14 GiB |
| `lc256` | 262,144 | 12288 + 4096 | 12 GiB | 20 GiB |
| `lc512` (experimental, ≈500K) | 524,288 | 12288 + 4096 | 22 GiB | 28 GiB |

Host KV quotas are generous over the estimate (2.3 / 4.5 / 9 / 18 GiB). `lc512` will
normally be refused on 32 GB RAM; it needs `--allow-experimental`.
Everything is overridable in Nix (`my.features.local-ai.longContext.*`).

## Extra option: IQ3 + Q4-class KV + KVMem 256K (`lc256-iq3`)

Requested as an additional option; the IQ4_XS presets above stay as they are.

- Preset: workspace 262,144, VRAM pool 32768 + 12288, KV `k8v4`, host KV 12 GiB, container 20 GiB.
- `k8v4` = K q8_0 / V q4_0. Opinion: better than plain `q4_0` (4-bit K and V), because
  K precision matters most for attention and retrieval; KVMem validates the mixed form. Plain
  `q4_0` stays selectable via `longContext.kvDtype` but is the most lossy.
- Estimated KV pool: 45,056 tokens x ~28 KiB = ~1.2 GiB. With IQ3 weights (~11 GiB, size
  unconfirmed) this should leave real headroom. This is the closest match to KVMem's own
  validated 16 GiB recipe (IQ3, 28K window, 256K). Still UNVERIFIED on gfx1030.
- **Blocked on pins:** the IQ3 file (revision, size, sha256) is not in `profiles.json` because
  Hugging Face was unreachable from the build session. `aibox plan lc256-iq3` and `ui
  --long-context lc256-iq3` refuse with a clear message until `qwen27-iq3` is added. Nothing is
  substituted. IQ3 is a quantization change you approved for this option only.
- The default Prism path accepts `my.features.local-ai.kvCacheType = "k8v4"` (or `"q4_0"`) for
  a larger plain context without KVMem. Quality impact is unmeasured.

## Safety behaviour

- `aibox start/ui --long-context PRESET` runs `plan` first: it refuses (exit with
  numbers) when free VRAM or RAM is below the estimate. **Nothing is reduced,
  offloaded or swapped automatically**; context, window and quantization are never
  changed. The VRAM/overhead constants are assumptions until measured.
- The container gets `--memory=N --memory-swap=N` (no swap), weights use
  `--load-mode none` (no mmap, no SSD tier), same rootless/read-only/cap-drop
  boundaries and internal network as before.
- Failures (`KVMEM_STARTUP_ERROR`, OOM, MTP inactive, missing mmproj) stop with logs;
  there is no fallback to text-only or MTP-off.

## Commands for nyx

```nix
# hosts/nyx/features.nix: my.features.local-ai.enable = true; then nx switch
```

```bash
aibox prepare --kvmem                      # builds the pinned KVMem HIP image (long)
aibox verify qwen27-iq4xs
aibox plan lc128                           # memory plan, starts nothing
aibox stop
aibox ui --profile qwen27-iq4xs --long-context lc64
aibox status ; aibox logs
aibox exec ~/projects/ki -- python3 /share/aibox/longctx_probe.py --tokens 48000
```

Repeat with `lc128` (probe `--tokens 110000`) and `lc256` (`--tokens 230000`). Record
VRAM with `cat /sys/class/drm/renderD128/device/mem_info_vram_used`
and RAM with `podman stats --no-stream nx-ai-inference` while running. For the baseline
use the unchanged path (`aibox ui --profile qwen27-iq4xs`) and the probe with
`--tokens 12000 --skip vision`. The probe covers needle retrieval at three depths,
streamed TTFT/decode rate with MTP statistics, a tool call and a red/blue image. For
real screenshots and agent loops use the UI/Codex manually.

## Rollback

```bash
aibox stop
aibox ui --profile qwen27-iq4xs            # the unchanged 16K Prism path
```

No file of the Prism image or the models changed; remove the long-context image with
`podman rmi localhost/nx-ai-kvmem:<tag>` if desired.

## Qwen3.8-Flash-Next (comparison only, not implemented)

Not benchmarked here. From the master-context notes: Strata runs Flash-Next (MoE) and
is not a dense-27B engine; a MoE needs the experts resident (RAM/GPU) and quantization
trade-offs apply per expert. Its context story is different (smaller active parameters,
cheaper long-context decode) but there are no comparable RX 6800 measurements and
quality for coding/vision is unmeasured. Recommendation: keep 27B + this mode as the
priority, and run Flash-Next through the existing `--strata` path as a separate
experiment with the same probe once the KVMem results exist.
