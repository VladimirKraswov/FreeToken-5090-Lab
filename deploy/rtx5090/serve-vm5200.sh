#!/usr/bin/env bash
set -euo pipefail

export FT_REPO_ROOT="${FT_REPO_ROOT:-/opt/freetoken/src/kai}"
export MODEL_DIR="${MODEL_DIR:-/srv/models/Qwen3.8-Flash-Next-NVFP4}"
export FT_BIN="${FT_BIN:-/opt/freetoken/venv/bin/ft}"
export FT_HOST="${FT_HOST:-0.0.0.0}"
export FT_PORT="${FT_PORT:-1919}"
export FT_CONTEXT_TOKENS="${FT_CONTEXT_TOKENS:-262144}"
export FT_KV_RESERVE_TOKENS="${FT_KV_RESERVE_TOKENS:-$FT_CONTEXT_TOKENS}"
export PATH="/usr/local/cuda/bin:/opt/freetoken/venv/bin:$PATH"

exec "$FT_REPO_ROOT/deploy/rtx5090/serve.sh" "$@"
