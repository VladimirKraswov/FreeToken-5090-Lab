# Target checkpoint and preserved features

- Repository: [RadixArk/Qwen3.8-Flash-Next-NVFP4](https://huggingface.co/RadixArk/Qwen3.8-Flash-Next-NVFP4).
- Download revision: `7b719225242aacd3dbd3f9407468c2ee9a9d2594`; all 419 local
  Hugging Face metadata entries agree on this revision. The machine-readable
  manifest records filenames, download ETags and sizes. ETags are not claimed
  as freshly recomputed SHA-256 checksums of every weight shard.
- Architecture: `Qwen4ExpForConditionalGeneration` / `qwen4_exp`; 48 layers,
  hidden size 2560, 512 routed experts, top-10 routing, GDN plus QSA sparse
  attention, one PLE layer (layer 2), n-gram size 3, 16 PLE hash heads.
- Checkpoint RoPE capacity: 262144. Selected **serving** context: **131072**,
  with BF16 KV; validated prompts exceed 100000 actual model tokens.
- `max_output_tokens=32768` is still constrained by total prompt+output capacity.
- Native Vision enabled, encoder weights in host RAM, image embedding cache on
  CPU, image limit 4096 tokens. Final functional validation used a 2048x2048
  image at the 4096 image-token cap, consuming 4120 total prompt tokens; the
  earlier 1536x1536 check consumed 2328. Neither proves every possible image.
- OpenAI chat, Responses and tool calling checked. API alias: `qwen38-flash-next`.
- Clients explicitly request reasoning effort `medium`; the API's native
  default for an omitted effort remains `xhigh`.
- Model sampling defaults: temperature 1.0, top-k 20, top-p 0.95. Benchmarks
  explicitly record temperature; most controlled comparisons use greedy 0.

This is the Flash Next MoE checkpoint, **not** the earlier dense 27B GGUF model.
The target weights and BF16 KV were not requantized. FreeToken-Kai's existing
MTP loader quantizes the checkpoint's draft-head BF16 routed experts to NVFP4
for its extra offload bank. This affects proposal efficiency; every proposed
token is checked by the target. Our work did not invent the MTP implementation.

The benchmark is not a comprehensive quality evaluation. Functional retrieval,
Vision, tools, tensor equivalence and state tests are evidence for these paths,
not proof of zero regressions on all prompts or all architectures.
