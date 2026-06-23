"""A/B test the tool-loop final-answer no_think lever (needs the model on :8765).

Single-mode: reads SENPAI_TOOLLOOP_NOTHINK once and runs the Assistant queries,
printing wall-clock latency + the answer. Run it twice (mode 0 then 1) and compare
the latency win against any quality/grounding change before flipping the default.

  SENPAI_USE_LLM=1 BASE_URL=http://127.0.0.1:8765/v1 SENPAI_TOOLLOOP_NOTHINK=0 \
      PYTHONUTF8=1 PYTHONUNBUFFERED=1 PYTHONPATH=. python scripts/toolloop_nothink_ab.py
"""
from __future__ import annotations
import json, os, sys, time
from fastapi.testclient import TestClient
from senpai import config
from senpai.api.server import app

QUERIES = [
    "値引きについて先輩の原則は？",
    "D001の健全度を見て",
    "決裁者が見えない案件、どう進めるべき？",
]

def run_turn(client, q):
    tools, ans, t0 = [], "", time.time()
    with client.stream("POST", "/api/chat",
                       json={"message": q, "history": [], "role": "junior"}) as r:
        buf = ""
        for ch in r.iter_text():
            buf += ch
            while "\n\n" in buf:
                f, buf = buf.split("\n\n", 1)
                ln = next((l for l in f.splitlines() if l.startswith("data:")), None)
                if not ln:
                    continue
                try:
                    ev = json.loads(ln[5:].strip())
                except Exception:
                    continue
                if ev.get("type") == "tool":
                    tools.append(ev["name"])
                elif ev.get("type") == "answer":
                    ans = ev.get("text", "")
    return time.time() - t0, tools, ans

def main():
    label = "NO_THINK" if config.TOOLLOOP_NO_THINK else "BASELINE"
    print(f"===== {label} (TOOLLOOP_NO_THINK={config.TOOLLOOP_NO_THINK}) =====", flush=True)
    client = TestClient(app)
    total = 0.0
    for q in QUERIES:
        dt, tools, ans = run_turn(client, q)
        total += dt
        print(f"\nQ: {q}\n  {dt:5.1f}s  tools={tools}", flush=True)
        print("  ANSWER:", ans[:300].replace("\n", " / "), flush=True)
    print(f"\nTOTAL {label}: {total:.1f}s", flush=True)

if __name__ == "__main__":
    main()
