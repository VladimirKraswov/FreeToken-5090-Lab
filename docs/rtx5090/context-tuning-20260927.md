# RTX 5090 serving-context selection, 2026-09-27

The selected standalone FreeToken window is **262,144 tokens**. This doubles the
previous 131,072-token profile while leaving the same Flash Next NVFP4
checkpoint, hybrid MoE, BF16 KV, 12 CPU expert workers, MTP3, Vision and
sampling settings in place. VM5100's V100 remains on its separate NInfer 27B
service. The configured window is a startup flag, not a model recompile.

## Comparable measurements

These trials used one RTX 5090, the same deterministic synthetic LRU-code
request, temperature 0, Medium reasoning, 512 requested output tokens,
`ignore_eos=true`, one active request and the same model. The only serving
capacity change was `--max-seq-len-override` and matching
`--kv-reserve-tokens`: 262,144 or 196,608. Each value had a fresh process and
the same warmup before testing. Decode uses API completion-token count divided
by the client's interval from the first to the last nonempty streamed delta;
TTFT is request start to the first nonempty delta. The report JSON is in
[`benchmarks/rtx5090/data/context-20260927/`](../../benchmarks/rtx5090/data/context-20260927/).

| Actual input / cache | Window | TTFT | Decode | Total |
| --- | ---: | ---: | ---: | ---: |
| 105,078 / cold | 262K | 42.76 s | 43.51 tok/s | 54.50 s |
| 105,078 / cold | 196K | 40.93 s | 47.69 tok/s | 51.65 s |
| 160,083 / cold | 262K | 62.99 s | 43.96 tok/s | 74.61 s |
| 160,083 / cold | 196K | 61.61 s | 46.16 tok/s | 72.68 s |
| 180,083 / cold | 196K | 66.87 s | 47.24 tok/s | 77.69 s |
| 240,083 / cold | 262K | 94.84 s | 43.35 tok/s | 106.63 s |

At equal 105K input the 196K window improved client decode by 9.6% and TTFT
by 4.3%; at equal cold 160K input it improved decode by 5.0% and TTFT by 2.2%.
The 180K row establishes a tested length for the 196K trial, but there is no
paired 262K run at that length. At 240K input, near the selected 262K window's
245,760-token OpenCode input cap, standalone 5090 decode was still 43.35 tok/s:
there was no observed halving of decode speed. TTFT rose to 94.84 s because
prefill processed more than twice as much input as the 105K case. A 160,078-token run
after the 105K case reused 105,024 prefix tokens on both processes; its TTFT
is in the raw data but is **not** used as a cold-prefill result. All numbers
are single runs, so small percentage differences are indicative, not a
statistical guarantee. The older 131K-window result at about 105K input was
collected on a different date and setup and is not an A/B control here.

The user chose the larger 262K capacity because a 2-5 tok/s difference at the
same prompt is an acceptable tradeoff for twice the original window. The
roughly 19.5 tok/s seen in an earlier two-VM pipeline must not be attributed
to standalone 5090 inference at 262K: placement and workload were different.
Reducing the KV floor to 196K also leaves more of the fixed VRAM budget to
FreeToken's automatic MoE cache; this is a plausible explanation for the
measured speed difference, not an isolated causal measurement. The 240K result
supports the capacity choice for this one workload; it does not establish
speed or answer quality at every possible prompt length and content.

## Operation and limits

The repository launcher `deploy/rtx5090/serve.sh` defaults to 262144 and reads
`FT_CONTEXT_TOKENS`; `FT_KV_RESERVE_TOKENS` defaults to the same number and
cannot be smaller. On VM5200, `/srv/freetoken/serve.sh` is the systemd entry
point and `/v1/models` should report `max_model_len: 262144`. The previous
entry point is backed up as
`/srv/freetoken/serve.sh.pre-context-20260927`. A restart is required for a
context change; no engine rebuild is needed. The OpenCode model declaration
must agree with the server so that client compaction and input limits are
accurate. The service's `--max-output-tokens 32768` remains an upper request
budget; prompt plus generated output must fit the chosen total context.

This setup uses nearly all 32 GiB of the RTX 5090. Around 240 MiB of NVML
memory was free during one 262K warm run. Do not increase concurrency, image limits
or KV reserve without repeating startup, long-context and Vision tests.
The separate final validation passed on the selected 262K profile: it recovered
all three exact facts placed at the beginning, middle and end of a 240,077-token
prompt; identified red in a 1536 × 1536 image; produced the requested tool
call; and returned the expected Responses API answer. The raw validation record
is [`validation-262k-long240.json`](../../benchmarks/rtx5090/data/context-20260927/validation-262k-long240.json).
These functional checks and throughput numbers do not prove general answer
quality preservation. The model weights and target/draft acceptance logic were
not changed. Different output hashes across some greedy runs show that
byte-for-byte generation equivalence is not established.
