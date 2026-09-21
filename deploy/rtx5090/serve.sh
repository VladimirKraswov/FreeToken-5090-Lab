#!/usr/bin/env bash
set -euo pipefail
repo_root="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
export PYTHONPATH="$repo_root/python${PYTHONPATH:+:$PYTHONPATH}"
export PYTORCH_ALLOC_CONF=expandable_segments:True
export OMP_NUM_THREADS="${OMP_NUM_THREADS:-32}"
exec "${FT_BIN:-ft}" serve --model "${MODEL_DIR:?Set MODEL_DIR to the checkpoint directory}" --gpu 0 --host "${FT_HOST:-127.0.0.1}" --port "${FT_PORT:-1919}" --served-model-name qwen38-flash-next --moe-strategy hybrid --expert-load parallel --moe-cache-auto --kv-reserve-tokens 131072 --max-seq-len-override 131072 --max-output-tokens 32768 --cache-type radix --sampling-defaults model --reasoning-parser qwen3 --tool-call-parser qwen3_coder --mm-encoder-weights host --mm-embed-cache-device cpu --image-max-tokens 4096 --max-running-requests 1 --enable-cache-report --decode-log-interval 20 --cors-origins '*' --moe-cpu-threads 12 --spec-mtp 3 --memory-ratio 0.87 --ple-backend pinned --prefill-mixer-pieces 2 --prefill-chunk-budget 0.85 --no-moe-collect-stats --moe-prefill-hit-d2d --max-prefill-length 14336 --quant-backend moe.nvfp4=triton "$@"
