"""Can prompt-engineering close the 8B's coaching-style gap (vs keeping the 27B)?

Hypothesis under test: the 8B Q4 holds grounding/factual fidelity; the only
regression is *writing style* (mechanical, repetitive, less mentor-like). If so,
a stronger synthesis prompt (+ few-shot) might let the 8B handle ALL synthesis —
FAST and THINK — making the hybrid (27B-for-THINK) unnecessary.

Method (frozen-context A/B, same as bench_synthesis so synthesis is isolated):
  * Freeze the post-tool context ONCE with the 27B selection loop per query
    (cached to disk → cheap prompt iteration).
  * Synthesize the identical frozen context with FOUR arms:
      control      : 27B            (no style booster)        — the bar
      8b_plain     : 8B Q4          (no style booster)        — today's gap
      8b_style     : 8B Q4 + STYLE_DIRECTIVE
      8b_fewshot   : 8B Q4 + STYLE_DIRECTIVE + 1 style exemplar
  * Run on BOTH regimes: the router's FAST queries and its THINK queries.

Per arm record: latency, prompt/completion tokens, decode tok/s, grounding
fidelity (veto metric), and style proxies (enumeration density, line-repetition).
Then a 27B *judge* scores each 8B arm's coaching quality 1–5 and picks pairwise
vs the 27B baseline (blind order). Nothing in the live path is touched.

Run:  python scripts/bench_synth_prompt.py \
        --candidate-base http://127.0.0.1:8766/v1 --candidate-model qwen3-8b \
        --queries 4 [--judge] [--refreeze]
"""
from __future__ import annotations

import argparse
import hashlib
import json
import random
import re
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from senpai.llm import synth_style
from scripts.bench_synthesis import (
    QUERIES, freeze_context, grounding_report, _make_client, _THINK, _PATTERNS,
)

_CACHE = Path(__file__).resolve().parent / ".freeze_cache"
ARMS = ["control", "8b_plain", "8b_style", "8b_fewshot"]
_ARM_MODE = {"8b_plain": "none", "8b_style": "style", "8b_fewshot": "fewshot"}

# Larger validation set — synthesis-producing scenarios across real seed entities,
# balanced FAST (grounded summary/restatement) vs THINK (coaching/analysis). The
# router decides the actual regime per query; the trailing tag is documentation.
QUERIES_BIG: list[tuple[str, str, str]] = [
    # ---- FAST: grounded summaries / overviews ----
    ("株式会社松田サービス（C28）の取引履歴と直近の状況をまとめて", "junior", "fast"),
    ("株式会社平和システム（C81）の案件一覧と各案件の状況を教えて", "junior", "fast"),
    ("豊田建設（C133）のIT環境と過去の案件を整理して", "junior", "fast"),
    ("有限会社村田印刷（C13）の案件D001の状況と直近の日報を教えて", "junior", "fast"),
    ("近藤電機（C96）について、過去のやり取りと案件をまとめて", "junior", "fast"),
    ("株式会社村田食品（C135）の取引状況と環境を教えて", "junior", "fast"),
    ("株式会社ヤマト食品（C09）の案件概要と顧客環境をまとめて", "junior", "fast"),
    ("有限会社ニュー食品（C76）の案件D003とD138の状況を確認したい", "junior", "fast"),
    # ---- THINK: deep coaching / cross-signal / risk ----
    ("松田サービス（C28）は案件が多い。どれを優先すべきか、理由とともに分析して", "junior", "think"),
    ("平和システム（C81）の案件群のリスクを評価し、共通の課題と打ち手を教えて", "junior", "think"),
    ("豊田建設（C133）は前進が遅い。なぜか、先輩としてどう動くべきか助言して", "junior", "think"),
    ("近藤電機（C96）の案件で決裁者に会えていない。どう対応すべきか考えて", "junior", "think"),
    ("いま危ない案件を挙げて、共通の原因と優先すべき打ち手を考えて", "manager", "think"),
    ("ヤマト食品（C09）の案件が停滞している。リスクと次の一手を整理して", "junior", "think"),
    ("村田食品（C135）の案件で競合と比較されている。何を強調すべきか、根拠も添えて", "junior", "think"),
    ("ニュー食品（C76）の案件、接触はあるが決まらない。なぜか分析して次の手を示して", "junior", "think"),
]


def grounding2(answer: str, context: str, query: str) -> dict:
    """Hardened grounding: separate TRUE fabrications (specific tokens absent from
    both the tool context and the user's own query) from over-abstraction (few
    specific tokens retained). `fidelity` is only meaningful with enough checked
    tokens, else None — a bare-prose answer no longer scores a misleading 0."""
    haystack = (context + " " + query).replace(",", "")
    fabrications, supported = [], 0
    for kind, pat in _PATTERNS.items():
        for tok in set(pat.findall(answer)):
            t = tok.replace(",", "").lstrip("¥")
            if t in haystack or tok in (context + query):
                supported += 1
            else:
                fabrications.append(f"{kind}:{tok}")
    checked = supported + len(fabrications)
    return {"fab_count": len(fabrications), "fabrications": fabrications,
            "specificity": supported,
            "fidelity": round(1 - len(fabrications) / checked, 3) if checked >= 3 else None}


def _retry(fn, what, tries=8, delay=12):
    """Retry a transport-fragile call across a tunnel reconnect window (~96s).
    The self-healing tunnel reconnects in seconds; this rides over the gap so a
    network blip retries instead of crashing the whole run."""
    last = None
    for k in range(tries):
        try:
            return fn()
        except Exception as e:  # noqa: BLE001
            last = e
            print(f"    ! {what} failed ({str(e)[:55]}) — retry {k + 1}/{tries} in {delay}s")
            time.sleep(delay)
    raise last


def _freeze_cached(query, role, ctrl_client, ctrl_model, refreeze: bool):
    _CACHE.mkdir(exist_ok=True)
    key = hashlib.md5(f"{ctrl_model}|{role}|{query}".encode()).hexdigest()[:16]
    fp = _CACHE / f"{key}.json"
    if fp.exists() and not refreeze:
        return json.loads(fp.read_text(encoding="utf-8"))
    frozen = freeze_context(query, role, ctrl_client, ctrl_model)
    fp.write_text(json.dumps(frozen, ensure_ascii=False), encoding="utf-8")
    return frozen


def _synth(client, model, frozen, mode):
    """Synthesize the frozen context with an optional style booster applied."""
    from senpai.llm.client import _prep
    convo = synth_style.apply(frozen["convo"], mode)
    msgs = _prep(convo, frozen["no_think"])
    t0 = time.perf_counter()
    resp = client.chat.completions.create(
        model=model, messages=msgs, temperature=0.0, max_tokens=1024)
    dt = time.perf_counter() - t0
    text = _THINK.sub("", resp.choices[0].message.content or "").strip()
    u = resp.usage
    comp = u.completion_tokens if u else len(text) // 3
    return {"text": text, "wall_s": round(dt, 1),
            "prompt_tokens": u.prompt_tokens if u else None,
            "completion_tokens": comp, "tok_s": round(comp / dt, 1) if dt else 0.0}


# --- style proxies (objective, automatable) ----------------------------------
def style_metrics(text: str) -> dict:
    lines = [l.strip() for l in text.splitlines() if l.strip()]
    bullets = sum(1 for l in lines if re.match(r"^([-*•]|\d+[.)、])", l))
    # line-repetition: fraction of non-unique line *prefixes* (field-dump tell)
    prefixes = [re.sub(r"[\s:：].*$", "", l)[:8] for l in lines if len(l) > 3]
    rep = 1 - len(set(prefixes)) / len(prefixes) if prefixes else 0.0
    words = re.findall(r"\w+", text)
    lex_rep = 1 - len(set(words)) / len(words) if words else 0.0
    return {"chars": len(text),
            "enum_density": round(bullets / len(lines), 2) if lines else 0.0,
            "line_rep": round(rep, 2), "lex_rep": round(lex_rep, 2)}


# --- 27B judge: blind pairwise coaching quality ------------------------------
_JUDGE_SYS = (
    "あなたは大塚商会のベテラン営業教育担当です。2つの回答(AとB)を、"
    "新人営業へのコーチングとしての質で評価します。重視点: 先輩らしい語り口、"
    "優先順位付け(列挙の羅列でない)、洞察(なぜ・次に何を)、簡潔さ、事実の正確さ。"
    "厳密にJSONのみで出力: {\"better\":\"A|B|tie\",\"a\":<1-5>,\"b\":<1-5>,\"why\":\"<20字以内>\"}"
)


def judge(ctrl_client, ctrl_model, query, ans_27b, ans_8b):
    """Blind pairwise: randomize which slot the 27B/8B occupy; map back."""
    flip = random.random() < 0.5
    a, b = (ans_8b, ans_27b) if flip else (ans_27b, ans_8b)
    prompt = (f"質問: {query}\n\n--- 回答A ---\n{a}\n\n--- 回答B ---\n{b}\n\n"
              "JSONで評価:")
    try:
        r = ctrl_client.chat.completions.create(
            model=ctrl_model, temperature=0.0, max_tokens=160,
            messages=[{"role": "system", "content": _JUDGE_SYS},
                      {"role": "user", "content": prompt},
                      {"role": "assistant", "content": "<think>\n\n</think>\n\n"}])
        raw = _THINK.sub("", r.choices[0].message.content or "")
        d = json.loads(raw[raw.find("{"): raw.rfind("}") + 1])
    except Exception as e:  # noqa: BLE001
        return {"better": "?", "score_8b": None, "score_27b": None, "err": str(e)[:40]}
    # un-flip: A/B back to model identity
    score_8b = d.get("a") if flip else d.get("b")
    score_27b = d.get("b") if flip else d.get("a")
    win = d.get("better")
    better_model = "tie" if win == "tie" else (
        ("8b" if (win == "A") == flip else "27b"))
    return {"better": better_model, "score_8b": score_8b, "score_27b": score_27b,
            "why": d.get("why", "")}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--candidate-base", default="http://127.0.0.1:8766/v1")
    ap.add_argument("--candidate-model", default="qwen3-8b")
    ap.add_argument("--queries", type=int, default=4)
    ap.add_argument("--judge", action="store_true")
    ap.add_argument("--refreeze", action="store_true")
    ap.add_argument("--big", action="store_true", help="use the 16-query validation set")
    args = ap.parse_args()

    from senpai import config
    ctrl = _make_client(config.BASE_URL)
    cand = _make_client(args.candidate_base)
    clients = {"control": (ctrl, config.MODEL)}
    for arm in ARMS[1:]:
        clients[arm] = (cand, args.candidate_model)

    # balance FAST + THINK. --big uses the full 16-query validation set.
    if args.big:
        sel = QUERIES_BIG
    else:
        n = args.queries
        sel = QUERIES[: n // 2] + QUERIES[-(n - n // 2):]
    print(f"control={config.MODEL}  candidate={args.candidate_model}  queries={len(sel)}\n")

    # Per-query checkpoint so a network blip (this box's tunnels are flaky) never
    # costs more than the current query. Completed rows are reloaded and skipped.
    ckpt = Path(__file__).resolve().parent / "bench_synth_prompt_checkpoint.json"
    rows = []
    done = set()
    if ckpt.exists() and not args.refreeze:
        try:
            rows = json.loads(ckpt.read_text(encoding="utf-8")).get("rows", [])
            done = {r["query"] for r in rows}
            print(f"resuming: {len(done)} queries already checkpointed\n")
        except Exception:  # noqa: BLE001
            rows = []

    for i, (q, role, hint) in enumerate(sel, 1):
        if q in done:
            print(f"[{i}/{len(sel)}] (cached) {q[:55]}")
            continue
        print(f"[{i}/{len(sel)}] ({hint}) {q[:60]}")
        frozen = _retry(lambda: _freeze_cached(q, role, ctrl, config.MODEL, args.refreeze), "freeze")
        print(f"    frozen: tools={frozen['tools']} mode={frozen['mode']} (select {frozen['select_s']:.0f}s)")
        row = {"query": q, "role": role, "hint": hint, "mode": frozen["mode"],
               "tools": frozen["tools"], "arms": {}}
        for arm in ARMS:
            cl, model = clients[arm]
            out = _retry(lambda: _synth(cl, model, frozen, _ARM_MODE.get(arm, "none")), f"synth:{arm}")
            g = grounding2(out["text"], frozen["grounding"], q)
            sm = style_metrics(out["text"])
            out.update({"fidelity": g["fidelity"], "fab_count": g["fab_count"],
                        "fabrications": g["fabrications"], "specificity": g["specificity"], **sm})
            row["arms"][arm] = out
            fid = f"{out['fidelity']:.2f}" if out["fidelity"] is not None else " NA "
            print(f"    {arm:11s} {out['wall_s']:5.1f}s {out['completion_tokens']:4d}tok "
                  f"{out['tok_s']:5.1f}t/s  fab={out['fab_count']} spec={out['specificity']:2d} "
                  f"fid={fid} enum={out['enum_density']:.2f} rep={out['line_rep']:.2f}")
        if args.judge:
            for arm in ARMS[1:]:
                j = _retry(lambda: judge(ctrl, config.MODEL, q, row["arms"]["control"]["text"],
                                         row["arms"][arm]["text"]), f"judge:{arm}")
                row["arms"][arm]["judge"] = j
                print(f"      judge {arm:11s} better={j['better']:4s} "
                      f"8b={j.get('score_8b')} 27b={j.get('score_27b')} {j.get('why','')}")
        rows.append(row)
        ckpt.write_text(json.dumps({"rows": rows}, ensure_ascii=False), encoding="utf-8")  # checkpoint

    # aggregate
    def avg(arm, key):
        vals = [r["arms"][arm][key] for r in rows if isinstance(r["arms"][arm].get(key), (int, float))]
        return round(sum(vals) / len(vals), 3) if vals else None

    summary = {"n": len(rows), "arms": {}}
    for arm in ARMS:
        s = {k: avg(arm, k) for k in ("wall_s", "completion_tokens", "tok_s",
                                      "fidelity", "fab_count", "specificity",
                                      "enum_density", "line_rep", "lex_rep")}
        if args.judge and arm != "control":
            js = [r["arms"][arm]["judge"] for r in rows if r["arms"][arm].get("judge")]
            s["judge_8b_avg"] = round(sum(j["score_8b"] for j in js if j.get("score_8b")) / len(js), 2) if js else None
            s["judge_27b_avg"] = round(sum(j["score_27b"] for j in js if j.get("score_27b")) / len(js), 2) if js else None
            s["wins_8b"] = sum(1 for j in js if j["better"] == "8b")
            s["wins_27b"] = sum(1 for j in js if j["better"] == "27b")
            s["ties"] = sum(1 for j in js if j["better"] == "tie")
        summary["arms"][arm] = s

    print("\n=== SUMMARY ===")
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    out_fp = Path(__file__).resolve().parent / "bench_synth_prompt_results.json"
    out_fp.write_text(json.dumps({"summary": summary, "rows": rows}, ensure_ascii=False, indent=2),
                      encoding="utf-8")
    print(f"\nfull side-by-side answers -> {out_fp}")


if __name__ == "__main__":
    main()
