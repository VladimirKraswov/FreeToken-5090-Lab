# RTX 5090 benchmark package

- `stream_bench.py`: stdlib streaming client, local or remote endpoint, gzip fixture support.
- `validate_final.py`: long-context retrieval, Vision, tools and Responses checks.
- `warmup.py`: the boot/restart warmup used by the deployment template.
- `verify_artifacts.py`: checks raw metric arithmetic, fixture identity and publication hygiene.
- `fixtures/`: immutable Apache-2.0 real-code prompt and its provenance.
- `data/all-results.csv`: combined historical and publication-audit table, including failed streams.
- `data/all-results.json`: the same full-precision table in JSON.
- `data/pre-audit-results.csv`: all 67 completed historical measurements, including marked invalid/warmup rows.
- `data/results/`: raw per-run measurements; three historical incomplete streams are retained as failures.
- `data/historical-profiles.json`: original profile settings, including discarded variants.
- `data/pre-audit-bounded-round.json`: paired real-code tuning round and selection.
- `data/model-manifest.json`: pinned checkpoint filenames, sizes and Hugging Face metadata.
- `data/runtime-versions.json`: measured Python package inventory.
- `data/research-index.json`: dated branch/issue discovery references.
- `data/tests/`: regression failures before fixes and passing CPU/GPU test results.

Read [the measurement guide](../../docs/rtx5090/measurement.md) before comparing rows.
TTFT from a cached prompt, a JIT warmup, and a fresh prompt are different metrics.
Audit and final-production results are added alongside the historical campaign.

```bash
python benchmarks/rtx5090/verify_artifacts.py
```
