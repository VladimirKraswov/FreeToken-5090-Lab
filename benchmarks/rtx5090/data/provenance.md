# Artifact provenance

Historical campaign: 2026-09-21, before the publication audit. Upstream control
was the installed FreeToken 0.1.3 wheel; Kai base was
`c206a6dfc614e983c57f71da391ff4ee76289ed2`.

| Audit label | Engine source |
|---|---|
| audit-baseline | `05a0ac7`: initial long-context fixes and disabled adaptive experiment |
| audit-fused | `45ad866`: adopted PLE hash plus fixed-shape invalidation, before the graph-lifetime fix |
| audit-cpu8 / audit-cpu16 / audit-mtp2 | `79b4dcb`: final graph-lifetime hardening; source files matched between local and deployed trees |
| audit-final-* | Same hardened engine; final publication commit only adds documentation, configuration and benchmark helpers |

`source-manifest.json` contains full SHA-256 hashes of the modified engine/test
files. `model-manifest.json` pins all checkpoint files to the download revision;
it records Hugging Face ETags and sizes, not freshly recomputed full-weight
checksums. `runtime-versions.json` records installed distributions. Runtime code
was imported via PYTHONPATH from the fork, while the installed distribution and
health API continued to report compatibility version 0.1.3.

Primary timing JSON comes from the stdlib SSE client. Model-generated response
previews and unrelated API request history are excluded from public data.
Output hashes remain for comparison. The full-precision JSON, rounded CSV and
Markdown tables have the same underlying measurements.

The three incomplete pre-audit streams were long-prefill OOM failures, not zero
speed results. They are retained with missing token/rate fields. Warmup and
contaminated samples are labeled in the combined table. Optional-reference test
skips and the reproduced upstream CPU/BLAS bit-equality failure are retained in
`tests/`, alongside the final passing run. The two local harness transport tests
are separate from the 135-test CUDA/CPU engine run; counts are not summed across
repeated overlapping suites.
