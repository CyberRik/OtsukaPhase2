#!/usr/bin/env bash
# Run the Senpai web stack: FastAPI bridge (:8000) + Next.js frontend (:3000).
# The bridge wraps the existing engines unchanged; the frontend talks to it.
#
#   scripts/run_web.sh            # starts both (Ctrl-C stops both)
#
# Requires: pip deps from requirements.txt, and `npm install` already run in web/.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
export SENPAI_TODAY="${SENPAI_TODAY:-2026-06-16}"
export PYTHONIOENCODING=utf-8

echo "▶ API   http://localhost:8000  (SENPAI_TODAY=$SENPAI_TODAY)"
( cd "$ROOT" && python -m uvicorn senpai.api.server:app --port 8000 ) &
API_PID=$!
trap 'kill $API_PID 2>/dev/null || true' EXIT

echo "▶ Web   http://localhost:3000"
( cd "$ROOT/web" && NEXT_PUBLIC_API_BASE="http://localhost:8000" npm run dev )
