# Coaching in Senpai

Senpai's coaching is a deterministic, grounded system that turns the deal-health
signals into something a **manager** and a **salesperson** actually use. Nothing here
invents advice: every output maps to a rule over the real SPR data, and every
"lesson" is an interview-cited principle a human approved.

## The pieces

| Surface | For | Module | What it does |
|---|---|---|---|
| **Review Coach** | rep | `coach/review.py` | Reads a rep's note, runs 5 *absence lenses* (decision-maker, timeline, criteria, next-step, budget) + stall/competitor detectors, returns 6 teaching sections — several options, never one "right answer". |
| **Coaching Workspace** | manager | `coaching.py` | Per-deal *needs-coaching* queue (7 issue rules), team trends, Confidence-vs-Reality. |
| **Rep coaching profile** | manager | `coach/profile.py` | **NEW** — a rep's *recurring* weaknesses across their whole book, for a 1:1. |
| **Rep progress** | manager | `coach/progress.py` | **NEW** — is the rep improving over fiscal years; was past coaching acted on. |
| **Coaching threads** | both | `data/seed/coaching_threads.json` | **NEW** — manager↔rep chat raised on a flagged deal (the conversational layer + the acted-on signal). |
| **Similar cases / Knowledge** | both | `coach/cases.py`, `knowledge/` | Real past win/loss cases + human-approved principles that ground every lesson. |

## Rep coaching profile — the 1:1 page

`rep_coaching_profile(employee_id)` aggregates the deterministic coaching issues
(`coaching.compute_issues`) across a rep's open deals into ranked, grounded weaknesses:

- ordered by **severity then frequency** (a missing decision-maker outranks report hygiene);
- each weakness carries: count + **real example deals**, a **validated principle**
  (`knowledge`), a **real past case** (`coach.cases`), and one **concrete action**;
- plus **strengths**, a headline **development focus** (with an explainability card),
  **1:1 talking points**, and the rep's **coaching-thread** status.

```bash
python -c "from senpai.coach.profile import rep_coaching_profile, team_coaching_profiles; \
import json; print(json.dumps(rep_coaching_profile('R12'), ensure_ascii=False, indent=2))"
```
API: `GET /api/coach/rep-profile/{employee_id}`, `GET /api/coach/rep-profiles` (team).

## Rep progress — is coaching landing?

`rep_progress(employee_id, windows=4)` replays the engine **as of each of the last
fiscal years** (scoring each deal at its last in-window activity, so staleness isn't
a false signal) to produce a per-issue **trend** and an overall headline
(改善傾向 / 横ばい / 悪化傾向). It joins `coaching_threads` to report whether past
coaching was **acted on** (resolved rate).

```bash
python -c "from senpai.coach.progress import rep_progress; print(rep_progress('R05'))"
```
API: `GET /api/coach/rep-progress/{employee_id}`.

## Why the demo is credible (not gimmicky)

The synthetic data is driven by a single deterministic **rep skill model**
(`data/gen_seed.py:REP_SKILL`): each rep has characteristic weakness themes (juniors
more, experts fewer) and some juniors are flagged **improving** (their notes get more
complete over fiscal years). The coaching engine then *rediscovers* those weaknesses
from the data — so a seeded decision-maker-weak rep surfaces `missing_decision_maker`,
and an improving discovery-weak rep visibly trends down. The loop is closed and
checkable.

The enrichment only rewrites three activity fields (`daily_report`,
`business_card_info`, `customer_challenge`) via a **local RNG keyed on each activity**,
so the SPR tables (deals/quotes/orders, amounts, dates, anchors) stay **byte-identical**.
Reports now span a realistic quality spread (≈26% thorough → tapering to thin), instead
of the old 28-char notes where every lens fired.

Regenerate + reindex:
```bash
SENPAI_TODAY=2026-06-16 python -m senpai.data.gen_seed     # writes seed incl. coaching_threads.json
SENPAI_TODAY=2026-06-16 python -m senpai.retrieval.build_index   # reports changed → refresh vectors
```

## Coaching threads (chat data)

`coaching_threads.json` holds short manager↔rep exchanges on flagged deals
(`issue_key`, `status ∈ {open, acknowledged, resolved}`, dated `messages`). Resolved
threads correlate with the rep's `improving` flag, giving `rep_progress` its acted-on
signal. Helpers: `store.coaching_threads_for_rep` / `coaching_threads_for_deal`.
API: `GET /api/coach/threads?rep_id=…|deal_id=…`.

## Tests
`tests/test_coaching_data.py` (data demonstrates the rules + byte-stability + anchors),
`tests/test_rep_profile.py` (grounding, severity ordering, team rollup, API),
`tests/test_progress.py` (improving rep trends down, acted-on join).
