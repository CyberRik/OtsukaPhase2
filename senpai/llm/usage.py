"""LLM token accounting — how much we spend on the local model, per inference.

Every completion call site in `senpai.llm.client` records one row here so the
admin portal can answer "tokens taken per prompt/response" and track usage over
time. Numbers are the server-reported `usage` from the OpenAI-compatible response
(the honest figure); when a backend omits usage on a streamed call we fall back to
a cheap local estimate and mark the row `estimated=True` so the UI never presents a
guess as measured.

Rows are appended as JSONL to `config.INGESTED_DIR/llm_usage.jsonl` (gitignored,
demo-only). Recording is best-effort and must never break an inference. Reads are
simple line scans — this is a low-volume demo log, not a metrics backend.
"""
from __future__ import annotations

import json
import os
import threading
from collections import defaultdict
from datetime import datetime, timezone
from typing import Any

from senpai import config

_LOG_PATH = config.INGESTED_DIR / "llm_usage.jsonl"
_LOCK = threading.Lock()

# Local models are effectively free; this is a labelled *estimate* knob for teams
# that still want a spend figure. Dollars per 1K total tokens.
COST_PER_1K_TOKENS = float(os.environ.get("SENPAI_LLM_COST_PER_1K", "0") or 0)


def _estimate_tokens(text: str) -> int:
    """Cheap, dependency-free token estimate for the fallback path: ~1 token per
    CJK character, ~1 per 4 other chars. Only used when the server reports no
    usage; rows built from it are flagged estimated=True."""
    if not text:
        return 0
    cjk = sum(1 for c in text if "　" <= c <= "鿿" or "＀" <= c <= "￯")
    other = len(text) - cjk
    return cjk + (other // 4)


def record(model: str, endpoint: str, prompt_tokens: int, completion_tokens: int,
           *, label: str | None = None, streamed: bool = False,
           estimated: bool = False) -> None:
    """Append one usage row. `endpoint` is 'primary'|'fallback'; `label` is the
    calling feature (e.g. 'chat', 'narrate', 'crew', 'graph_rag_demo'). Never
    raises."""
    try:
        prompt_tokens = int(prompt_tokens or 0)
        completion_tokens = int(completion_tokens or 0)
        row = {
            "ts": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "model": model,
            "endpoint": endpoint,
            "label": label or model,
            "prompt_tokens": prompt_tokens,
            "completion_tokens": completion_tokens,
            "total_tokens": prompt_tokens + completion_tokens,
            "streamed": streamed,
            "estimated": estimated,
        }
        line = json.dumps(row, ensure_ascii=False)
        with _LOCK:
            config.INGESTED_DIR.mkdir(parents=True, exist_ok=True)
            with _LOG_PATH.open("a", encoding="utf-8") as fh:
                fh.write(line + "\n")
    except Exception:  # noqa: BLE001 — accounting must never break inference
        pass


def record_response(resp: Any, *, model: str, endpoint: str,
                    label: str | None = None, streamed: bool = False) -> None:
    """Record from an OpenAI-compatible response's `.usage`. No-op (silently) if
    usage is absent — callers on the streaming path use record(..., estimated=True)
    instead."""
    usage = getattr(resp, "usage", None)
    if usage is None:
        return
    record(model, endpoint,
           getattr(usage, "prompt_tokens", 0) or 0,
           getattr(usage, "completion_tokens", 0) or 0,
           label=label, streamed=streamed)


# --- aggregation (reads) ---------------------------------------------------
def _rows() -> list[dict]:
    if not _LOG_PATH.exists():
        return []
    out = []
    try:
        for line in _LOG_PATH.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line:
                try:
                    out.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
    except Exception:  # noqa: BLE001
        return out
    return out


def _totals(rows: list[dict]) -> dict:
    return {
        "calls": len(rows),
        "prompt_tokens": sum(r.get("prompt_tokens", 0) for r in rows),
        "completion_tokens": sum(r.get("completion_tokens", 0) for r in rows),
        "total_tokens": sum(r.get("total_tokens", 0) for r in rows),
        "estimated_calls": sum(1 for r in rows if r.get("estimated")),
        "est_cost": round(sum(r.get("total_tokens", 0) for r in rows) / 1000 * COST_PER_1K_TOKENS, 4),
    }


def _group(rows: list[dict], key: str) -> list[dict]:
    buckets: dict[str, list[dict]] = defaultdict(list)
    for r in rows:
        buckets[str(r.get(key, "?"))].append(r)
    out = [{key: k, **_totals(v)} for k, v in buckets.items()]
    out.sort(key=lambda d: d["total_tokens"], reverse=True)
    return out


def summary(*, recent_n: int = 50) -> dict:
    """Everything the admin usage page needs: totals, per-day trend, by-model,
    by-feature, and the most recent individual inferences."""
    rows = _rows()
    # collapse ts→date for the day trend
    day_buckets: dict[str, list[dict]] = defaultdict(list)
    for r in rows:
        day_buckets[str(r.get("ts", ""))[:10]].append(r)
    by_day = [{"day": d, **_totals(v)} for d, v in sorted(day_buckets.items())]
    return {
        "totals": _totals(rows),
        "cost_per_1k": COST_PER_1K_TOKENS,
        "by_day": by_day,
        "by_model": _group(rows, "model"),
        "by_label": _group(rows, "label"),
        "recent": rows[-recent_n:][::-1],
    }
