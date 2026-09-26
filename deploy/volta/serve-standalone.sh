#!/usr/bin/env bash
set -euo pipefail

repo_root="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
export PYTHONPATH="$repo_root/python${PYTHONPATH:+:$PYTHONPATH}"
export PATH="/usr/local/cuda-12.9/bin:$PATH"
export PYTORCH_ALLOC_CONF=expandable_segments:True

model_dir="${MODEL_DIR:?Set MODEL_DIR to the shared checkpoint directory}"
bank_dir="${FT_V100_BANK_DIR:?Set FT_V100_BANK_DIR to a local writable bank directory}"
if [[ ! -f "$model_dir/config.json" || ! -d "$bank_dir" || ! -w "$bank_dir" ]]; then
  printf 'The checkpoint and a writable local bank directory must exist\n' >&2
  exit 2
fi
if systemctl is-active --quiet ninfer-v100.service; then
  printf 'Stop ninfer-v100.service before a standalone FreeToken trial on this GPU\n' >&2
  exit 2
fi

# The NVFP4 bank needs about 63.5 GiB; leave room for a partial file and metadata.
if [[ ! -f "$bank_dir/bank.ftmb" ]]; then
  free_kib="$(df -Pk "$bank_dir" | awk 'NR == 2 {print $4}')"
  if [[ ! "$free_kib" =~ ^[0-9]+$ ]] || (( free_kib < 70 * 1024 * 1024 )); then
    printf 'At least 70 GiB free is required for the V100 expert bank\n' >&2
    exit 2
  fi
fi

context_tokens="${FT_CONTEXT_TOKENS:-65536}"
if [[ ! "$context_tokens" =~ ^[1-9][0-9]*$ ]]; then
  printf 'FT_CONTEXT_TOKENS must be a positive integer\n' >&2
  exit 2
fi

exec "${FT_BIN:-/opt/freetoken-v100/venv/bin/ft}" serve \
  --model "$model_dir" --gpu 0 --host "${FT_HOST:-127.0.0.1}" \
  --port "${FT_PORT:-19290}" --served-model-name qwen38-flash-next-volta \
  --moe-strategy hybrid --expert-load serial --moe-cache-auto \
  --moe-bank-ram "${FT_BANK_RAM:-24G}" --moe-bank-dir "$bank_dir" \
  --kv-reserve-tokens "$context_tokens" --max-seq-len-override "$context_tokens" \
  --max-output-tokens 8192 --max-running-requests 1 --cache-type radix \
  --sampling-defaults model --reasoning-parser qwen3 --tool-call-parser qwen3_coder \
  --mm-encoder-weights host --mm-embed-cache-device cpu --image-max-tokens 4096 \
  --moe-cpu-threads 8 --memory-ratio 0.82 --ple-backend disk \
  --max-prefill-length 8192 --quant-backend moe.nvfp4=triton "$@"
