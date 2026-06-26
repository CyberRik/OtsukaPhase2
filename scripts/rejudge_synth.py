"""Re-run only the 27B coaching-quality judge over cached bench_synth_prompt
answers (no re-synthesis). Fixes the judge message ordering and re-scores."""
from __future__ import annotations
import json, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from senpai import config
from scripts.bench_synthesis import _make_client
from scripts.bench_synth_prompt import judge, ARMS

RES = Path(__file__).resolve().parent / "bench_synth_prompt_results.json"


def main():
    d = json.loads(RES.read_text(encoding="utf-8"))
    ctrl = _make_client(config.BASE_URL)
    agg = {a: {"8b": [], "27b": [], "win": []} for a in ARMS[1:]}
    for r in d["rows"]:
        print(f"\n{r['mode']:5s} {r['query'][:55]}")
        base = r["arms"]["control"]["text"]
        for arm in ARMS[1:]:
            j = judge(ctrl, config.MODEL, r["query"], base, r["arms"][arm]["text"])
            r["arms"][arm]["judge"] = j
            if j.get("score_8b"):
                agg[arm]["8b"].append(j["score_8b"]); agg[arm]["27b"].append(j["score_27b"])
                agg[arm]["win"].append(j["better"])
            print(f"  {arm:11s} better={j['better']:4s} 8b={j.get('score_8b')} "
                  f"27b={j.get('score_27b')} {j.get('why','')}")
    print("\n=== JUDGE SUMMARY (8B coaching score vs 27B baseline, 1-5) ===")
    for arm in ARMS[1:]:
        s8, s27, win = agg[arm]["8b"], agg[arm]["27b"], agg[arm]["win"]
        if not s8:
            print(f"{arm:11s}: no valid judgements"); continue
        print(f"{arm:11s}: 8B={sum(s8)/len(s8):.2f}  27B={sum(s27)/len(s27):.2f}  "
              f"wins 8b/27b/tie = {win.count('8b')}/{win.count('27b')}/{win.count('tie')}")
    RES.write_text(json.dumps(d, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\nupdated -> {RES}")


if __name__ == "__main__":
    main()
