"""Live end-to-end conversation-caching test (needs the model on :8765).

Drives the real bridge in-process via TestClient and parses the SSE stream so we
see the actual `context`/`cached` flags AND that real tokens stream from the LLM.

  SENPAI_USE_LLM=1 BASE_URL=http://127.0.0.1:8765/v1 PYTHONUTF8=1 PYTHONPATH=. \
      python scripts/live_cache_test.py
"""
from __future__ import annotations
import json, re
from fastapi.testclient import TestClient
from senpai.api.server import app

client = TestClient(app)

def sse(path: str, body: dict):
    """POST and yield parsed SSE event dicts."""
    with client.stream("POST", path, json=body) as r:
        buf = ""
        for chunk in r.iter_text():
            buf += chunk
            while "\n\n" in buf:
                frame, buf = buf.split("\n\n", 1)
                line = next((l for l in frame.splitlines() if l.startswith("data:")), None)
                if line:
                    try:
                        yield json.loads(line[5:].strip())
                    except Exception:
                        pass

def collect(path, body):
    ctx, deltas, types = None, 0, []
    for ev in sse(path, body):
        t = ev.get("type"); types.append(t)
        if t == "context":
            ctx = ev
        elif t == "delta":
            deltas += 1
    return ctx, deltas, types

CID = "live-test-conv-1"

print("=== REVIEW COACH narrate cache ===")
note = "村田印刷を訪問。担当者と次回の打ち合わせ日程を調整中。価格面の懸念あり。"
for label, body in [
    ("#1 first",     {"note": note, "deal_id": "D001", "narrate": True, "lang": "ja", "conversation_id": CID}),
    ("#2 same",      {"note": note, "deal_id": "D001", "narrate": True, "lang": "ja", "conversation_id": CID}),
    ("#3 note chg",  {"note": note + " 追記：競合が入った。", "deal_id": "D001", "narrate": True, "lang": "ja", "conversation_id": CID}),
]:
    ctx, deltas, types = collect("/api/coach/narrate", body)
    cached = ctx.get("cached") if ctx else None
    print(f"  {label:<10} cached={cached!s:<5} deltas={deltas:<4} grounded={ctx.get('grounded') if ctx else '?'} "
          f"customer={ctx.get('customer') if ctx else '?'}")

print("\n=== ASSISTANT chat account-carry cache ===")
CID2 = "live-test-conv-2"
turns = [
    ("names 村田印刷", "村田印刷の状況を教えて。次に何をすべき？"),
    ("follow-up 1",    "リスクは何？"),
    ("follow-up 2",    "直近の動きは？"),
]
hist = []
for label, msg in turns:
    ctx, deltas, types = collect("/api/chat", {"message": msg, "history": hist, "role": "junior", "conversation_id": CID2})
    cust = (ctx or {}).get("customer")
    cust_s = cust.get("name") if isinstance(cust, dict) else cust
    print(f"  {label:<16} cached={(ctx or {}).get('cached')!s:<5} customer={cust_s} deltas={deltas} "
          f"toolcalls={types.count('tool')}")
    hist.append({"role": "user", "content": msg})
    hist.append({"role": "assistant", "content": "(prev answer)"})

print("\nDONE")
