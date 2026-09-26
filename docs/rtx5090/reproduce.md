# Reproduction and operation

This package targets Linux, one RTX 5090, approximately 160 GiB guest RAM and
the exact RadixArk checkpoint. Commands assume a CUDA-capable build host and
the software versions in [hardware.md](hardware.md). The complete installed
version inventory is in `benchmarks/rtx5090/data/runtime-versions.json`.

## Obtain the code and checkpoint

```bash
git clone --branch rtx5090 https://github.com/VladimirKraswov/FreeToken-5090-Lab.git
cd FreeToken-5090-Lab
# For exact reproduction, checkout the commit recorded with the benchmark run.
uv venv --python 3.12 .venv
source .venv/bin/activate
uv pip install torch==2.11.0 --index-url https://download.pytorch.org/whl/cu130
uv pip install -e '.[accel]' transformers==5.16.1 pillow pytest
export PATH=/usr/local/cuda/bin:$PATH
MAX_JOBS=8 python setup.py build_ext --inplace

export MODEL_DIR=/srv/models/Qwen3.8-Flash-Next-NVFP4
hf download RadixArk/Qwen3.8-Flash-Next-NVFP4 \
  --revision 7b719225242aacd3dbd3f9407468c2ee9a9d2594 \
  --local-dir "$MODEL_DIR"
```

The install commands describe the measured stack; inspect resolver output
against `deploy/rtx5090/observed-versions.txt`. That file is an inventory, not a
portable lockfile: GPU wheels and system toolkit compatibility matter. No
model weights, access tokens, compiled extensions or GPU-specific JIT cache
are redistributed in this repository.

The new audit changes are Python/Triton only. The native extension build above
is needed for a fresh install; subsequent Triton kernels compile during tests
and warmup. Persist the service user's cache across restarts.

## Place CPU and memory near the GPU

Use `lspci -vv`, `/sys/bus/pci/devices/.../numa_node`, `lscpu -e` and
`numactl --hardware` on your own host before selecting CPUs. The measured VM
uses 32 vCPUs on host physical cores 0-15 plus their SMT siblings 40-55, with
160 GiB memory bound to NUMA0 and ballooning disabled. The GPU is on NUMA0.
These numeric CPU IDs are a topology example, not a portable affinity command.

Apply the 500 W cap after the device is attached and driver loaded:

```bash
sudo nvidia-smi -i 0 -pl 500
ft bench bw --gpu 0 --dtype nvfp4
```

Run calibration as the same account that serves the model. The default
GPU-specific `~/.cache/freetoken/benchbw/` file is discovered automatically.
If using `ft bench bw -o`, export `FREETOKEN_BENCHBW_PATH` in the service as
well. Confirm the start log reports a calibrated hybrid fetch fraction.

## Serve and warm

```bash
export FT_BIN="$PWD/.venv/bin/ft"
bash deploy/rtx5090/serve.sh
```

The template binds to loopback; set `FT_HOST` for your existing private service
network. API base is `http://<inference-host>:1919/v1`, model
`qwen38-flash-next`. The launcher now defaults to 262144 context (set
`FT_CONTEXT_TOKENS` to change it without rebuilding FreeToken), BF16 KV, MTP=3,
12 CPU expert workers, hybrid execution, pinned PLE, 14336-token prefill,
two mixer pieces, 0.85 prefill budget, memory ratio 0.87, hit-D2D and the
Triton NVFP4 backend. It accepts trailing option overrides for controlled trials.
The context selection and paired measurements are in
[context-tuning-20260927.md](context-tuning-20260927.md). Set
`FT_KV_RESERVE_TOKENS` only if the KV floor must exceed the serving window;
the launcher rejects a smaller floor.

`deploy/rtx5090/freetoken-qwen.service.example` and `rtx5090.env.example` show
the permanent service layout. Set the actual user, checkout, environment and
checkpoint paths before installing. The working directory must be writable by
the service account. Integrate the existing GPU power-limit service with
`Requires`/`After` as appropriate for the host.

`ExecStartPost` calls `warmup.py` on **every** model-process start. It exercises
greedy and sampled decoding, a 16000-token prompt (covering a complete 14336
prefill chunk) and Vision. Thus service startup waits for representative JIT
and graph work, not just an HTTP socket. Warmup does not precompile every
possible image or shape. Earlier measurements show a cold process load and
warmup takes roughly three minutes; this is not a VM reboot measurement.

The lab also keeps an external health watchdog enabled. It checks repeatedly
and only restarts after consecutive failures, not because a long prefill has
yet to emit a token. The model, expert banks and PLE remain loaded while idle.
The media VM must be stopped before assigning the same passthrough GPU here.

## Correctness checks

Stop the serving process before GPU unit tests; do not compete for its almost
full VRAM. The CPU thread setting makes the inherited bit-equality snapshot
test reproducible; production workers remain unchanged.

```bash
OMP_NUM_THREADS=1 MKL_NUM_THREADS=1 PYTHONPATH=python \
  python -m pytest -q \
  tests/distributed/test_spec_mtp.py \
  tests/models/qwen4_exp/test_ple.py \
  tests/models/qwen4_exp/test_gdn.py \
  tests/moe/test_prefill_invalidate.py \
  tests/moe/test_prefill_hit_d2d.py
```

After starting and warming the service:

```bash
export FT_BASE=http://127.0.0.1:1919
export FT_VALIDATION_OUT=validation.json
python benchmarks/rtx5090/validate_final.py
```

This checks exact values at the start/middle/end of a >100K-token prompt,
a red image (1536x1536 by default; `FT_VISION_SIZE=2048` for the larger audit probe), a structured tool call and the Responses API. It exits
nonzero on failure and writes each result as it completes.

## Measure client throughput

From the same client machine for both sides of an A/B comparison:

```bash
python benchmarks/rtx5090/stream_bench.py \
  --base http://127.0.0.1:1919 --label real-code \
  --lengths 0 --tokens 1024 --repeats 2 --seed audit-pair \
  --temperature 0 \
  --prompt-file benchmarks/rtx5090/fixtures/real-code-prompt.txt.gz \
  --output ./benchmark-output
```

The harness itself has two CPU-only transport regressions:

```bash
python benchmarks/rtx5090/test_stream_bench.py
python benchmarks/rtx5090/verify_artifacts.py
```

They check empty-role versus first-token timing, reasoning deltas, rejection of
an incomplete stream, metric arithmetic and the frozen fixture hash.

Repeat with `--temperature 1` for normal model sampling. `--lengths 0,75000,105000`
without a prompt file reproduces the synthetic padding/LRU-code workload.
For authenticated deployments set `FT_API_KEY` in the environment.

Each benchmark uses `ignore_eos=true` to hold output length constant; functional
tests do not. A repeated seed on the same live server may reuse its prefix.
For **fresh** comparisons, restart and warm each variant before using the
same nonce sequence, or choose new nonces and record the difference. Check
server cache-hit counts; a cached TTFT is not a fresh TTFT.

The script writes raw arrival times, API usage, finish reason, output hash and
text. Keep generated outputs private if using your own prompts. Published lab
artifacts omit response previews and unrelated request history. Our fixed
fixture contains only open-source code and a synthetic question.

## Controlled toggles and rollback

Change one dimension at a time and keep model/context/sampling unchanged:

- `--moe-cpu-threads 8` / `12` / `16`.
- `--spec-mtp 2` / `3`; depth 5 and adaptive 2–4 were also tested earlier.
- `--moe-hybrid-max-fetch 4` / `8`, compared against calibrated auto.
- `--max-prefill-length 10240` / `12288` / `14336`.
- `FREETOKEN_PLE_FUSED_HASH=0` disables the adopted PLE hash fusion.
- `FREETOKEN_PREFILL_INVALIDATE_FUSED=0` disables fixed-shape invalidation.
- `FT_SPEC_ADAPTIVE=1` requires `--spec-mtp 4`; it is experimental and not
  enabled by the production launcher.

Preserve a known-good launcher and source commit before a trial. On failure,
stop the process, restore that launcher/commit, restart, warm and run functional
validation. Switching Python files underneath a running process does not update
the already imported engine. Restore the watchdog after maintenance.

## Repository CI

The fork's GitHub Actions workflow checks the benchmark artifacts, streaming
client and launcher syntax on a hosted CPU runner. It does not claim to rerun
the GPU model tests. Inherited upstream release/nightly/issue-label workflows
are disabled in this fork; no automated wheel publishing is configured.
The homelab is not attached as a GitHub Actions runner.

## Pi and VS Code agent operation

The later [Pi autonomy integration](../../integrations/pi/README.md) addresses
per-response output exhaustion with Low/16384 and one bounded recovery turn.
It includes configuration merge examples, deployment instructions and CPU-only
SDK tests. It does not change the Medium benchmark protocol above.
