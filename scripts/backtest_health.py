"""Outcome backtest / calibration harness for deal-health scoring.

The deal-health score is a HEURISTIC (hand-set weights + band cutoffs). The only
way to know whether it's a *predictive* risk signal is to check it against real
outcomes: do high-risk deals actually lose more often than low-risk ones?

This harness does exactly that — it scores every CLOSED deal, treats lost
(DEAD_RANKS) as the event and won (WON_RANKS) as the non-event, and reports:

  • mean/median risk for won vs lost,
  • AUC — P(a lost deal scores riskier than a won deal); 0.5 = no signal, 1.0 = perfect,
  • a calibration table: for each band (and raw-score bucket), the ACTUAL loss rate.

⚠️  On the SYNTHETIC seed this only validates *internal consistency* (does the score
    separate the outcome labels the generator baked in?) — it says nothing about the
    real world. Point it at real historical deals (ideally scored from a snapshot
    *before* close, to avoid leakage) to get a genuine calibration. The report layout
    is identical, so the same command works on real data.

Run:  SENPAI_TODAY=2026-06-16 PYTHONPATH=. python3 scripts/backtest_health.py
"""
from __future__ import annotations

import os
from statistics import mean, median

os.environ.setdefault("SENPAI_TODAY", "2026-06-16")
os.environ.setdefault("SENPAI_USE_EMBEDDINGS", "0")

from senpai import config
from senpai.data import store
from senpai.health.scoring import score_deal


def auc(pos: list[float], neg: list[float]) -> float:
    """AUC via Mann-Whitney U with tie handling. pos = event (lost), neg = won."""
    n_pos, n_neg = len(pos), len(neg)
    if not n_pos or not n_neg:
        return float("nan")
    labelled = sorted([(s, 1) for s in pos] + [(s, 0) for s in neg], key=lambda x: x[0])
    ranks = [0.0] * len(labelled)
    i = 0
    while i < len(labelled):
        j = i
        while j < len(labelled) and labelled[j][0] == labelled[i][0]:
            j += 1
        avg = (i + 1 + j) / 2.0           # average 1-based rank over the tie group
        for k in range(i, j):
            ranks[k] = avg
        i = j
    sum_pos = sum(r for r, (_, lab) in zip(ranks, labelled) if lab == 1)
    u = sum_pos - n_pos * (n_pos + 1) / 2.0
    return u / (n_pos * n_neg)


def bar(frac: float, width: int = 24) -> str:
    n = int(round(frac * width))
    return "█" * n + "·" * (width - n)


# --- score every deal, split by outcome ------------------------------------
won_scores: list[float] = []
lost_scores: list[float] = []
rows = []   # (deal_id, score, band, outcome)
for d in store.all_deals():
    rank = d.get("order_rank")
    if rank in config.WON_RANKS:
        outcome = "won"
    elif rank in config.DEAD_RANKS:
        outcome = "lost"
    else:
        outcome = "open"
    res = score_deal(d, store.activities_for_deal(d["deal_id"]))
    rows.append((d["deal_id"], res.score, res.band, outcome))
    if outcome == "won":
        won_scores.append(res.score)
    elif outcome == "lost":
        lost_scores.append(res.score)

closed = won_scores + lost_scores
n_closed = len(closed)

print("=" * 64)
print("  DEAL-HEALTH OUTCOME BACKTEST  (⚠ synthetic data — internal check only)")
print("=" * 64)
print(f"\nDeals: {len(rows)} total | closed {n_closed} "
      f"(won {len(won_scores)}, lost {len(lost_scores)}) | open {len(rows) - n_closed}")

# --- separation -------------------------------------------------------------
print("\n--- Risk score by outcome (higher = riskier) ---")
if won_scores:
    print(f"  WON  : mean {mean(won_scores):5.1f}  median {median(won_scores):5.1f}  n={len(won_scores)}")
if lost_scores:
    print(f"  LOST : mean {mean(lost_scores):5.1f}  median {median(lost_scores):5.1f}  n={len(lost_scores)}")
gap = (mean(lost_scores) - mean(won_scores)) if (won_scores and lost_scores) else float("nan")
print(f"  Separation (lost − won mean): {gap:+.1f}  "
      f"→ {'lost score riskier ✓' if gap > 0 else 'NO separation ✗'}")

a = auc(lost_scores, won_scores)
quality = ("strong" if a >= 0.75 else "moderate" if a >= 0.65 else
           "weak" if a >= 0.55 else "≈ random")
print(f"\n  AUC (risk predicts loss): {a:.3f}  ({quality})")
print("    0.5 = no signal · 0.7 = useful · 0.8+ = strong")

# --- calibration by band ----------------------------------------------------
print("\n--- Calibration: actual loss rate by band (closed deals only) ---")
print("  band     n   lost  loss-rate")
for band in ("red", "yellow", "green"):
    sub = [r for r in rows if r[2] == band and r[3] in ("won", "lost")]
    n = len(sub)
    lost = sum(1 for r in sub if r[3] == "lost")
    rate = lost / n if n else 0.0
    print(f"  {band:<6} {n:4d}  {lost:4d}   {rate:5.1%}  {bar(rate)}")
print("  (monotonic red ≥ yellow ≥ green loss-rate ⇒ bands rank risk correctly)")

# --- calibration by raw-score bucket ---------------------------------------
print("\n--- Calibration: loss rate by score bucket ---")
buckets = [(0, 10), (10, 25), (25, 40), (40, 55), (55, 75), (75, 101)]
print("  score      n   lost  loss-rate")
for lo, hi in buckets:
    sub = [r for r in rows if lo <= r[1] < hi and r[3] in ("won", "lost")]
    n = len(sub)
    lost = sum(1 for r in sub if r[3] == "lost")
    rate = lost / n if n else 0.0
    print(f"  {lo:>3}-{hi - 1:<3} {n:5d}  {lost:4d}   {rate:5.1%}  {bar(rate)}")

# --- verdict ---------------------------------------------------------------
print("\n--- Read-out ---")
mono = True
prev = -1.0
for band in ("green", "yellow", "red"):
    sub = [r for r in rows if r[2] == band and r[3] in ("won", "lost")]
    rate = (sum(1 for r in sub if r[3] == "lost") / len(sub)) if sub else 0.0
    if rate < prev - 1e-9:
        mono = False
    prev = rate
print(f"  • bands rank risk monotonically: {'YES ✓' if mono else 'NO ✗'}")
print(f"  • score discriminates outcomes (AUC>0.65): {'YES ✓' if a >= 0.65 else 'NO ✗'}")
print("  • NOTE: synthetic data — re-run on real, snapshot-before-close history to")
print("    calibrate the weights/cutoffs for production. This harness is that tool.")
print("=" * 64)
