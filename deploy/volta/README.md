# Single-GPU deployment and Volta validation

This lab uses two **independent** inference services. VM5200 (`192.168.31.71`)
serves Qwen3.8 Flash Next NVFP4 on its RTX 5090 with FreeToken. VM5100
(`192.168.31.93`) serves the 27B Huihui-abliterated NVFP4 checkpoint on its
Tesla V100 with NInfer. There is no pipeline, remote MoE executor, or inference
request that needs both GPUs. Keep the services independent when changing either
model or its context limit.

## Live services and rollback

| Host | Service | Endpoint | Model |
| --- | --- | --- | --- |
| VM5200 | `freetoken-qwen.service` | `http://192.168.31.71:1919` | `qwen38-flash-next` |
| VM5100 | `ninfer-v100.service` | `http://192.168.31.93:8080` | `qwen-v100` |

The effective V100 systemd unit includes
`/etc/systemd/system/ninfer-v100.service.d/10-huihui-uncensored.conf` and loads
`/srv/ninfer-v100-lab/models/huihui-abliterated/qwen3_8_27b_huihui_abliterated_nvfp4.ninfer`.
Do not infer the live checkpoint from the base unit alone: the drop-in overrides
`ExecStart`. Verify with `systemctl cat ninfer-v100.service`, `systemctl
is-active ninfer-v100.service`, `curl http://192.168.31.93:8080/v1/models`, and
a short completion. On 2026-09-27 the endpoint returned `qwen-v100`, 262,144
maximum context, and answered `7+5` with `12`.

VM5200's launch command is `/srv/freetoken/serve.sh`. Its installed source is
`/opt/freetoken/src/kai`, Python is `/opt/freetoken/venv/bin/python`, and the
watchdog is `freetoken-watchdog.timer`. Before changing the launch command, save
a dated copy and record the current Git SHA. After a restart, check both
`systemctl is-active freetoken-qwen.service freetoken-watchdog.timer` and
`curl http://127.0.0.1:1919/health`; `active` alone can precede model readiness.
To roll back, restore the saved launch command/source, restart the service, and
repeat the health and short-completion checks. Preserve both model checkpoints.

## Optional FreeToken experiments on V100

The Flash Next checkpoint lives only on VM5200 at
`/srv/models/Qwen3.8-Flash-Next-NVFP4`. VM5100 has a read-only NFSv4.2 mount at
`/mnt/qwen-5090` and a symlink at the same `/srv/models/...` path. Verify with
`sudo exportfs -v` on VM5200 and `findmnt /mnt/qwen-5090` on VM5100. This is
one checkpoint shared for **alternative** single-GPU launches, not a two-GPU
runtime. The V100 FreeToken source and virtual environment are under
`/opt/freetoken-v100`, separate from production NInfer.

V100 needs CUDA 12 rather than CUDA 13 because the latter does not target
`sm_70`. The tested lab stack was CUDA 12.9, PyTorch 2.9.1+cu128, and Triton
3.5.1; `requirements.txt` records the Python packages. `flashlib==0.3.0` was
installed with a dependency override because its declared Triton minimum is
newer than the version pinned by that PyTorch release. The relevant FreeToken
backend is `--quant-backend moe.nvfp4=triton`, not the hardware NVFP4 or b12x
backend. The script `validate_expert.py` checks real NVFP4 checkpoint experts
against a float32 dequantized reference; it is a kernel test, not a full-model
serve test.

The tested V100 results were:

- Triton NVFP4 decode backend: 5 GPU tests passed, including FP16 and BF16.
- Qwen attention/GDN/PLE subset: 54 passed, 4 skipped. One PLE CPU comparison
  needed `atol=1e-6` because the PyTorch 2.9 reduction order changed by
  4.77e-7.
- Actual checkpoint experts: layer 0/expert 0 maximum absolute FP16 error
  9.38e-6; layer 47/expert 511 1.35e-5, both within their float32 tolerances.

These checks establish a useful Volta NVFP4 compute path. They do **not**
establish that Flash Next can serve end-to-end on V100 today. Its 48-layer,
512-expert bank is about 63.5 GiB; VM5100 has only about 22 GiB free on root
and about 47 GiB available RAM while NInfer is running. A full host/disk bank
cannot be provisioned there without additional storage and memory planning.
Any future standalone trial must first provide a local bank filesystem with
adequate free space, stop only NInfer for the trial, verify model load and
long-context/Vision behavior, and restore NInfer afterward. Do not replace the
read-only checkpoint symlink with a second 130 GiB copy.

`serve-standalone.sh` is the guarded trial launcher. It refuses to run while
NInfer owns the V100, requires a writable local bank directory with at least
70 GiB free for a first build, uses the CUDA 12.9 environment and the Triton
NVFP4 kernel, and defaults to disk-backed PLE to avoid pinning a roughly
47.7 GiB table in VM5100's RAM. Once the missing storage is provisioned, a
trial can set `MODEL_DIR=/srv/models/Qwen3.8-Flash-Next-NVFP4` and
`FT_V100_BANK_DIR=<local-directory>` and run the script after stopping NInfer.
The script is a launch option, **not** proof of full-model correctness or
production performance; NInfer remains the V100 production service.

## Why the two-GPU prototype was retired

The same Qwen Flash Next checkpoint, 131,080 actual input tokens, 256 output
tokens, temperature 0, Medium reasoning, MTP3 and 262,144 configured context
were used in the comparison. Client-side records are in `results/`.

| Placement | TTFT | Decode | Total |
| --- | ---: | ---: | ---: |
| RTX 5090 + CPU/DDR4 | 54.45 s | 40.74 tok/s | 60.71 s |
| RTX 5090 + V100, 44/4 pipeline | 203.14 s | 22.74 tok/s | 214.36 s |

The pipeline slowed decode by 44% and prefill by 3.7x. A separate one-bank
V100 RPC microbenchmark reached 1.198 ms median / 1.246 ms p95 round-trip,
but a full 1,024-token continuation was 40.21 tok/s remotely versus 42.16
tok/s on one 5090. The short 256-token trial showed a 2.4% gain that did not
survive the longer run. These experiments do not justify shipping cross-VM
transport. The abandoned transport and pipeline code were removed; the useful
per-layer timing sampler and V100 NVFP4 validation remain.

The single-GPU profiler's ten sampled MTP steps on a 131K-prefix continuation
averaged 76.81 ms per step: route 0.99, expert fetch 57.78, GPU expert work
3.83, uncovered CPU wait 2.04 and other 12.17 ms. One MTP step can emit more
than one token, so these are not per-token timings. Use the retained per-layer
sampling to decide what to optimize within a single host, and compare changes
at identical model, prompt, output length, and serving context.
