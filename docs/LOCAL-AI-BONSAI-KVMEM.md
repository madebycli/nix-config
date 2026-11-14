# Bonsai 2 27B PQ2_0 + KVMem: 256K logical context

**Status:** Preset and CLI integration implemented. **Not verified on the RX 6800 with real Bonsai weights.**
Upstream KVMem's published Bonsai tests used PTQ1 with a different Q4 MTP head on NVIDIA. They do not prove this exact ProCreations PQ2_0 + Q8_0 MTP GGUF, the Q8_0 projector, HIP/gfx1030 or image input work.

## Scope

- Separate opt-in preset: `lc256-bonsai`. Exact profile `bonsai27-pq2`, never Qwen or a different quantization.
- Pinned KVMem revision: `deb8e76582892a3f6f61bae0b728701b3b41cce7`, llama.cpp base `cd959bae99ff4bed22bef2604f45241c09bbb8c8`.
- Pinned `prepare-backends.py` patches include PQ2_0 (type 142, group 128), CPU/CUDA kernels (used for the HIP build), Bonsai Hadamard/MTP support. The build checks the PQ2 type registration and GPU kernel path explicitly.
- Model: ProCreations/Ternary-Bonsai-2-27B-MTP PQ2_0 + trained Q8_0 MTP head. Projector: prism-ml/Ternary-Bonsai-2-27B-gguf Q8_0. Both remain SHA256-pinned in `pkgs/aibox/profiles.json`.
- Logical workspace 262,144 tokens with selective KVMem retrieval, **not** 262K tokens of full GPU attention.
- Physical GPU KV working pool: 32,768 history + 12,288 generation = 45,056 tokens.
- Host KV quota: 12,288 MiB; container memory limit: 20,480 MiB and no swap.
- K/V cache Q8_0 + MTP draft Q8_0, up to two proposed draft tokens, replay state; one slot.
- Matching image projector is attached but executes on CPU. Image processing is a separate acceptance test.
- Inference stays rootless with only read-only weights and the selected GPU render node; API published only to localhost by `aibox ui`.
- Original 16K Prism Bonsai and both Qwen profiles are unchanged.

## Activate on nyx

Use the branch containing this feature (or merge it into main), then:

```bash
nx pull
nixctl on local-ai       # only if currently disabled
nx switch
aibox prepare --kvmem    # HIP build on demand; does not download weights
aibox fetch bonsai27-pq2 # skip if already downloaded
aibox verify bonsai27-pq2
aibox plan lc256-bonsai  # explicit memory plan; refuses insufficient resources
aibox stop               # if another profile is running
aibox ui --profile bonsai27-pq2 --long-context lc256-bonsai
```

The UI binds to `http://127.0.0.1:8766`. For private API without UI, use
`aibox start --profile bonsai27-pq2 --long-context lc256-bonsai`.

## Real-device acceptance

```bash
aibox status
aibox logs
# Replace this with an existing user-owned project directory:
aibox exec ~/projects/ki -- python3 /share/aibox/longctx_probe.py --tokens 8000
aibox exec ~/projects/ki -- python3 /share/aibox/longctx_probe.py --tokens 48000
# On successful 48K retrieval, move to 110K and finally 230K:
aibox exec ~/projects/ki -- python3 /share/aibox/longctx_probe.py --tokens 110000
aibox exec ~/projects/ki -- python3 /share/aibox/longctx_probe.py --tokens 230000
podman stats --no-stream nx-ai-inference
cat /sys/class/drm/renderD128/device/mem_info_vram_used
```

Record successful model load, GPU residency, real MTP acceptance, needle retrieval at different depths, vision, tool calls, prefill and decode times. The controller checks health and the MTP sampler, **not** correctness of these features. If the Q8 projector or PQ2/MTP is incompatible with HIP, the server may exit; no silent text-only or alternate-model fallback is allowed.

Do not assume the generic KV size or 1,700 MiB compute-overhead estimate exactly predicts this Bonsai workload. If the memory planner rejects startup, change the budget only as an explicit, reviewed Nix setting, not by weakening checks automatically.

## Rollback

```bash
aibox stop
aibox ui --profile bonsai27-pq2
```

This preserves the pinned Prism 16K path without deleting the downloaded Bonsai model or container images.

## Technical sources

- [Pinned KVMem Bonsai integration](https://github.com/kvmem/kvmem/blob/deb8e76582892a3f6f61bae0b728701b3b41cce7/docs/bonsai-integration.md)
- [Pinned KVMem patch manifest](https://github.com/kvmem/kvmem/blob/deb8e76582892a3f6f61bae0b728701b3b41cce7/backends/versions.json)
- [Prism Bonsai GGUF format support](https://github.com/PrismML-Eng/Bonsai-demo/blob/main/BACKEND-SUPPORT.md)
