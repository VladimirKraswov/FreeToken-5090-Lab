# Fork, branch and issue review

Reviewed on **2026-09-21**, before publishing this fork's changes. The search
covered upstream branches, the first 100 newest and 100 most-starred forks,
60 recently updated repositories with FreeToken in the name, and upstream
Qwen/MTP/hybrid issue and PR searches. Selected candidates were inspected at
commit and source-diff level. This is a scoped survey, not a claim that every
fork on GitHub was tested.

The upstream head was `cc1f5c2c91855f2cc7787ad6b909f7e46a5d5825`.
FreeToken-Kai's `kai` branch remained at
`c206a6dfc614e983c57f71da391ff4ee76289ed2`, already incorporating that upstream
head. Updating to those branches alone would not add a new optimization.

| Candidate | Finding and decision |
|---|---|
| [FreeToken-Kai](https://github.com/yuuki-net/FreeToken-Kai/tree/c206a6dfc614e983c57f71da391ff4ee76289ed2) | Selected base: existing Flash Next MTP draft/verify, rollback, graphs, Vision and QSA work. These are Kai's contributions, not ours. |
| [Native MTP request #421](https://github.com/FlashML-org/FreeToken/issues/421) | Still open. Stock FreeToken 0.1.3 must not be described as having the Kai Qwen MTP path. |
| [PLE hash PR #338](https://github.com/FlashML-org/FreeToken/pull/338), `de77d16a5ac3` | Adopted with author attribution, then fixed captured-index lifetime across shape-cache eviction. New regression fails on the original patch. Only one PLE layer in this checkpoint, so kernel speedup is not whole-model speedup. |
| [Prefill synchronization issue #501](https://github.com/FlashML-org/FreeToken/issues/501) | The same boolean-indexing operation exists in our base. Implemented a small fixed-shape invalidation kernel, retaining the reference path. Regression confirms removal of `aten::nonzero`; full serving tests decide the actual benefit. The report's 10–40x slowdown is not claimed for our machine. |
| [GDN convolution PR #339](https://github.com/FlashML-org/FreeToken/pull/339), `eea4ad6821ae` | Removes a host read in the Triton fallback. Our installation uses `sgl_kernel`; that specific fallback is not on the selected path. The Kai wrapper already accepts the optional host length. No wholesale merge for a non-applicable path. |
| [KV ladder PR #300](https://github.com/FlashML-org/FreeToken/pull/300), `1b90e9fc97a7` | Can rebalance expert/KV capacity for short requests. Our target is sustained 100K+ input with a permanently warm 131K allocation; ladder short-context numbers do not establish a benefit at the same final geometry. |
| [Long-context client throughput #306](https://github.com/FlashML-org/FreeToken/issues/306) | Not reproduced as a universal 75K cliff. Empty role events must not count as the first token. Our client and server metrics for the same requests agree. |
| [b12x/SM120 issue #335](https://github.com/FlashML-org/FreeToken/issues/335) | Still open; reports graph capture and batch-shape failures. Keep the explicitly selected Triton NVFP4 backend. |
| [Hybrid calibration #308](https://github.com/FlashML-org/FreeToken/issues/308) | A custom `ft bench bw -o` file may not be discovered. Our profile is in the actual service user's default GPU-specific cache; start logs confirm dynamic calibrated fetch, not silent cap=1. |
| [Chunk checkpoint PR #505](https://github.com/FlashML-org/FreeToken/pull/505) | Kai already carries checkpoint-watermark fixes (`c145c776fe09`); avoid duplicating them. |
| [Hybrid refactor #491](https://github.com/FlashML-org/FreeToken/pull/491) | Primarily structural and stacked on ROCm work; no claimed algorithmic speedup applicable to this CUDA run. |
| [Adaptive DSpark PR #71](https://github.com/FlashML-org/FreeToken/pull/71) | Uses measured verification cost and proposal confidence, a better general objective than acceptance thresholds alone. It depends on a DeepSeek-specific stack and is not a drop-in Qwen patch. A future Qwen port needs its own state/distribution tests. |
| [DFlash PR #258](https://github.com/FlashML-org/FreeToken/pull/258) | Results are for another Qwen architecture, a separate draft model and an H20. No compatible, validated Flash Next draft checkpoint was established. |
| [JUNQINGV587 fork](https://github.com/JUNQINGV587/FreeToken/tree/79a0fa3233d6f9dfc6bdcd0a333f4427e9fbfcd4) | Inspected `sm89-moe-offload` and experimental branches. Two L20 GPUs, TP/P2P and SM89 wide-load kernels explain much of its result; they are not directly transferable to one SM120 card. Its PLE work points to #338 above. `exp/hc-prefill-fusion` describes its own result as small and shelved. |
| [FreeRoll](https://github.com/lzxlchlcx/FreeToken-FreeRoll/tree/analysis/expert-prediction-hit8), `90c7d43eaad5` | Expert-prediction measurement tools, not an already validated faster serving replacement. |
| [Frequency pinning #174](https://github.com/FlashML-org/FreeToken/issues/174) | Better cache hit rate on DSV4 did not translate to a large hybrid throughput benefit even in the report. No assumption that it will solve this Qwen profile. |
| [vektory79 fork](https://github.com/vektory79/FreeToken/tree/vektory79), `849010ba7f5e` | Additional hybrid prefix-cache lifecycle work. Potentially useful for conversational reuse; not evidence for faster fresh 105K decode. Changes overlap sensitive Kai snapshot logic, so not blindly merged. |
| [Windows Flash Next fork](https://github.com/brz6699/freetoken-win-qwen3.8-flash-next/tree/6800d6dbada5), `6800d6dbada5` | Uses quantized/tiered KV and Windows-specific residency. Its MTP experiment was negative; aggregate concurrent throughput cannot be compared with our single-request rate. We preserve BF16 KV. |
| [Ox boost](https://github.com/Cerynitius/freetoken-ox-boost/tree/b6888110f11f), `b6888110f11f` | Latest optimization chain targets DSV4/GLM on different hardware. Model-specific attention/compressor patches are not a Flash Next replacement. |
| [perryh deployment](https://github.com/perryh/qwen3.8-flash-next-nvfp4-freetoken/tree/3febdd71d4e9) | Useful memory-layout comparison, but the fast profile uses 16K context; the full-context profile is slower. Does not satisfy our same-profile 100K+ comparison. |
| [Gamal-ElDeen benchmarks](https://github.com/Gamal-ElDeen/FreeToken-serving-nvidia-Qwen3.8-Flash-Next-NVFP4-on-RTX5090-32GB-VRAM-with-128-DDR5) | Reports higher rates with a modern Core Ultra/DDR5 platform and the NVIDIA checkpoint. Their tokenizer caveat and aiperf results are documented. It shows that higher numbers exist; it does not prove a missing software flag on our Xeon/Gen3 system. |

## Remaining model-specific directions

1. A cost-aware Qwen MTP controller could optimize emitted tokens per measured
   millisecond, instead of maximizing acceptance. Our simple 2–4 threshold
   controller remains an unsuccessful, opt-in experiment.
2. Eliminate additional per-draft host reads only after profiling and preserving
   GDN/QSA rollback and page allocation. This is a substantial scheduling change,
   not a safe parameter toggle.
3. Measure prefix-reuse workloads separately. Fresh 105K prompts and repeated
   agent turns exercise different bottlenecks; #501 and snapshot work motivate
   that distinction.
4. Another hardware memory path (newer PCIe/DDR or more modern VRAM) may change
   the optimum. The measured Gen3 H2D rate is already close to its link budget.

No lower-precision target weights or KV, context reduction, extra GPU, untested
kernel backend, or pruning of experts was used to inflate the selected result.
There is no defensible proof of a global optimum over every possible kernel and
configuration. The claim is **best verified profile in the recorded experiments**.
