#!/usr/bin/env bash
# Serve the merged exp3 model as an OpenAI-compatible endpoint for the demo.
# Reuses the exact flags proven in src/toolcall_lm/eval/taubench_runner.py
# (Qwen3 emits Hermes-style <tool_call> JSON → --tool-call-parser hermes).
#
# Needs the GPU free (it's busy while exp5 synthetic gen runs).
#
# Usage:
#   ./demo/serve_demo.sh                 # serves the merged exp3 model on :8765
#   MODEL=/path/to/other_merged ./demo/serve_demo.sh
#   PORT=8001 ./demo/serve_demo.sh
set -euo pipefail

# This demo folder was copied into a new project, but the model weights and the
# vllm/CUDA venv still live in the original ToolCallLM_finetune project. Point at
# them by absolute path (override with VENV= / MODEL= if they ever move).
VENV=${VENV:-/home/team-a/Desktop/ToolCallLM_finetune/.venv}
MODEL=${MODEL:-/home/team-a/Desktop/ToolCallLM_finetune/ToolCallLM/outputs/merged_toolmind_exp3_final}
PORT=${PORT:-8765}

# Fail loudly with a clear message instead of a cryptic vllm/venv error.
[ -d "$MODEL" ] || { echo "error: model not found at MODEL=$MODEL" >&2; exit 1; }
[ -f "$VENV/bin/activate" ] || { echo "error: vllm venv not found at VENV=$VENV" >&2; exit 1; }

# shellcheck disable=SC1091
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
