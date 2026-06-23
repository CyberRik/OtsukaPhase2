#!/usr/bin/env bash
# Serve the merged exp3 model as an OpenAI-compatible endpoint for Senpai.
# Thin mirror of demo/serve_demo.sh — the junior chat needs this; the dashboard
# and tests do NOT (they are pure-Python and GPU-free).

set -euo pipefail

VENV=${VENV:-/home/team-a/Desktop/ToolCallLM_finetune/.venv}
MODEL=${MODEL:-/home/team-a/Desktop/ToolCallLM_finetune/ToolCallLM/outputs/merged_toolmind_exp3_final}
PORT=${PORT:-8765}

[ -d "$MODEL" ] || { echo "error: model not found at MODEL=$MODEL" >&2; exit 1; }
[ -f "$VENV/bin/activate" ] || { echo "error: vllm venv not found at VENV=$VENV" >&2; exit 1; }

source "$VENV/bin/activate"
export PATH="$VENV/bin:/usr/local/cuda/bin:$PATH"

exec vllm serve "$MODEL" \
  --served-model-name exp3 \
  --port "$PORT" \
  --dtype auto \
  --max-model-len 8192 \
  --gpu-memory-utilization 0.85 \
  --trust-remote-code \
  --enable-auto-tool-choice \
  --tool-call-parser hermes
