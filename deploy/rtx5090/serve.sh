#!/usr/bin/env bash
set -euo pipefail
repo_root="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
export PYTHONPATH="$repo_root/python${PYTHONPATH:+:$PYTHONPATH}"
export PYTORCH_ALLOC_CONF=expandable_segments:True
export OMP_NUM_THREADS="${OMP_NUM_THREADS:-32}"
context_tokens="${FT_CONTEXT_TOKENS:-262144}"
kv_reserve_tokens="${FT_KV_RESERVE_TOKENS:-$context_tokens}"
running_requests="${FT_MAX_RUNNING_REQUESTS:-3}"
graph_max_bs="${FT_CUDA_GRAPH_MAX_BS:-3}"
if [[ ! "$context_tokens" =~ ^[1-9][0-9]*$ || ! "$kv_reserve_tokens" =~ ^[1-9][0-9]*$ ]] ||
   (( kv_reserve_tokens < context_tokens )); then
  printf 'FT_CONTEXT_TOKENS and FT_KV_RESERVE_TOKENS must be positive integers; KV reserve must cover context\n' >&2
  exit 2
fi
if [[ ! "$running_requests" =~ ^[1-9][0-9]*$ ]]; then
  printf 'FT_MAX_RUNNING_REQUESTS must be a positive integer\n' >&2
  exit 2
fi
if [[ ! "$graph_max_bs" =~ ^[1-9][0-9]*$ ]]; then
  printf 'FT_CUDA_GRAPH_MAX_BS must be a positive integer\n' >&2
  exit 2
fi

exec "${FT_BIN:-ft}" serve \
  --model "${MODEL_DIR:?Set MODEL_DIR to the checkpoint directory}" \
  --gpu 0 --host "${FT_HOST:-127.0.0.1}" --port "${FT_PORT:-1919}" \
  --served-model-name qwen38-flash-next \
  --moe-strategy hybrid --expert-load parallel --moe-cache-auto \
  --kv-reserve-tokens "$kv_reserve_tokens" \
  --max-seq-len-override "$context_tokens" --max-output-tokens 32768 \
  --cache-type radix --sampling-defaults model \
  --reasoning-parser qwen3 --tool-call-parser qwen3_coder \
  --mm-encoder-weights host --mm-embed-cache-device cpu --image-max-tokens 4096 \
  --max-running-requests "$running_requests" --cuda-graph-max-bs "$graph_max_bs" \
  --scheduler-policy "${FT_SCHEDULER_POLICY:-prefill-first}" \
  --scheduler-decode-burst-ms "${FT_SCHEDULER_DECODE_BURST_MS:-500}" \
  --scheduler-decode-burst-steps "${FT_SCHEDULER_DECODE_BURST_STEPS:-64}" \
  --enable-cache-report --decode-log-interval 20 \
  --cors-origins '*' --moe-cpu-threads 12 --spec-mtp 3 --memory-ratio 0.87 \
  --ple-backend pinned --prefill-mixer-pieces 2 --prefill-chunk-budget 0.85 \
  --no-moe-collect-stats --moe-prefill-hit-d2d --max-prefill-length 14336 \
  --quant-backend moe.nvfp4=triton "$@"
