# Frozen real-code fixture

The gzip expands to the exact UTF-8 prompt used in the measurements. SHA-256:
`2aa13fecf38c5f26b79b7e7b981d2aaf240e384744e395ee64f3bf7945cfe804`.
It contains Apache-2.0 FreeToken/FreeToken-Kai source excerpts (MoE, engine and
scheduler), frozen before the adaptive experiment, plus a question about CPU/GPU
overlap. The repository LICENSE applies. It contains no private project source.
Do not regenerate it from a moving checkout for an A/B comparison.

The source excerpt has 104800 tokenizer tokens; the whole prompt before the
chat template has 104852. The nonce and template bring measured input to
104868 or 104870 in these campaigns. Always use the API's actual usage count.
