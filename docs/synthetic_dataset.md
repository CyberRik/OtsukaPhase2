# Synthetic Dataset Reference

The Senpai demo runs on **synthetic data** generated to match Otsuka's real SPR schema.
We have no real SPR access yet, so `senpai/data/gen_seed.py` produces a byte-stable seed
in exactly the production shape — when real data lands, it's a drop-in replacement and
nothing downstream changes.

- **Generator:** `senpai/data/gen_seed.py`
- **Output:** `senpai/data/seed/*.json` (committed to git)
- **Regenerate:** `python -m senpai.data.gen_seed`
- **Ground-truth schema:** [`Schema.md`](../Schema.md) — the four SPR tables are mirrored
  field-for-field; everything else is supplementary.

## Determinism

Output is reproducible: fixed RNG seed (`random.Random(42)`) + a fixed anchor date
`REFERENCE_DATE = 2026-06-16` (`senpai/config.py`). Regenerating twice yields byte-identical
files. For a reproducible run of the app/tests against this seed, pin scoring's "today":

```bash
export SENPAI_TODAY=2026-06-16
```

## What's in the seed

| File | Rows | SPR? | What it is |
|---|---:|:--:|---|
| `deals.json` | 520 | ✅ | Opportunity-level records (financials, ranks, dates) |
| `sales_activities.json` | 2,337 | ✅ | Activity log / daily reports (~3–6 per deal) |
| `quotes.json` | 480 | ✅ | Quotes for deals that progressed past prospecting |
| `orders.json` | 280 | ✅ | Order lines (one per confirmed/won deal) |
| `customers.json` | 150 | — | SMB customer master (Japanese names, industry, size) |
| `reps.json` | 24 | — | Sales reps (resolved from `sales_info.employee_id`) |
| `products.json` | 29 | — | Product master (`major/mid/minor`, pricing, specs) |
| `environments.json` | 150 | — | Customer IT environment (one per customer; SPR gap) |
| `playbook.json` | 31 | — | Coaching entries mined from `daily_report` |
| `customer_aliases.json` | 150 | — | English/romaji name forms (auto-derived) |
| `rank_history.json` | 1,612 | — | Order-rank change log (one row per change) |

> ✅ = mirrors a real SPR table field-for-field. The four SPR tables carry **no** invented
> columns. (`deals.json` also carries a handful of pre-existing **legacy alias** fields —
> `stage`, `amount`, `status`, … — used only by the separate web-app experiment; see the
> note at the bottom of `Schema.md`.)

## Time model (multi-year, anchored)

Everything is dated relative to `REFERENCE_DATE` (2026-06-16). Deals fall into three dated
cohorts so the *live* views stay bounded while history accumulates across **FY2023–FY2026**
(Japanese fiscal year starts in April):

| Cohort | Count | `order_rank` | Dating | Purpose |
|---|---:|---|---|---|
| Live pipeline | 140 | `2_A+`…`6_P` (open) | within ~0–90 days of anchor | Drives the dashboard, scoring, Matsuda demo |
| Historical won | 280 | `1_Confirmed` | spread across prior fiscal years | Order/revenue history, trend/manager views |
| Historical dead | 100 | `7_Lost` / `8_Cancelled` | spread across prior years | Loss history |

`store.open_deals()` filters to the open ranks, so the live pipeline a manager sees stays
~140 even though the corpus is 520.

**`order_rank` distribution:** `1_Confirmed` 280 · `2_A+` 20 · `3_A` 29 · `4_B` 37 ·
`5_C` 33 · `6_P` 21 · `7_Lost` 90 · `8_Cancelled` 10.
**Activity fiscal-year spread:** FY2024 ~874 · FY2025 ~778 · FY2026 ~684 (+ a 2023 tail).

## Content & catalog

- **Language:** data content is Japanese (customer/rep/product names, deal names, daily
  reports, playbook); field names stay English to match the SPR schema.
- **Customers:** ~150 SMBs, weighted toward 小規模, ~75% with no web presence. Names are
  composed from Japanese stem + suffix parts (`gen_seed.py` `_STEM` / `_SUFFIX`).
- **Products (29) across 7 majors:** OA機器 (6), PC周辺機器 (5), サーバー (2), ストレージ (2),
  ネットワーク機器 (5), ソフトウェア (6), 役務/保守 (3). Revenue is split into hw/sw/paid-service
  buckets by category (`_split_revenue`).
- **Reps (24):** R01–R08 + R09–R24, spread over 3 営業部 × 法人課, mixed roles
  (senior/expert/junior) and `is_top_performer`, with `specialty_tags` aligned to the catalog.
- **Daily reports:** varied Japanese narratives, including stall phrases that the scorer's
  `STALL_LEXICON` detects (`検討します`, `予算が`, `時期を見て`, …) and category-flavored lines.

## `rank_history.json` (order-rank change log)

A **separate** normalized table (not a column on `deals`, to keep `deals.json` field-for-field
with the SPR schema). Models the full rank trail the SPR export doesn't currently expose.

```json
{ "deal_id": "D141", "rank": "5_C", "changed_at": "2024-08-07" }
```

Per deal, rows are ordered oldest→newest and satisfy: first row's `rank` =
`deals.initial_order_rank` at `rank_first_registered_at`; last row's `rank` =
`deals.order_rank` at `rank_updated_at`. Trails show progression (`6_P→5_C→3_A→…`),
regression (`2_A+→4_B`), or death (`…→7_Lost`). The deal-health scorer reads only
`initial_order_rank` + `order_rank` + `rank_updated_at`, so this table is **additive** — safe
to drop in/out when real history arrives.

## `customer_aliases.json` (cross-language resolution)

Auto-derived from each customer's name parts (romaji + English forms), so a rep can type a
customer in English/romaji and `store.resolve_customer` finds the canonical JA record. Short
stem-only forms are intentionally shared across customers — the resolver treats a name that
maps to >1 customer as **ambiguous** and refuses to guess, so only specific forms resolve.

## Stable anchors (don't break these)

A few entities are pinned so tests and the Matsuda demo keep working; the large random
population is generated around them:

| Anchor | Why |
|---|---|
| `D001`–`D004` deliberately dead (strong rank, stale, order date passed, no decision-maker) | Manager view flags real risk on first load; `D003` is a known close-date-passed flag |
| `D001` customer = 有限会社村田印刷 (`C13`) | Asserted by a draft-message test |
| `C28` = 株式会社松田サービス, rich open pipeline | Default account for the Matsuda demo (`build_matsuda_context`) |
| Reps `R01`–`R08` unchanged (esp. `R05` = 伊藤翔) | Asserted by coaching/summary tests |
| "Aozora Services" resolves uniquely; "Yamato Trading" is ambiguous | Alias-resolution tests |

## Verify

```bash
export SENPAI_TODAY=2026-06-16
python -m senpai.data.gen_seed                 # regenerate (byte-stable)
pytest -q                                      # full suite (no GPU)
python demo_matsuda.py                         # Matsuda context + 10 Q&A → report.md
python -m senpai.tools.impl                    # one canned call per manager tool
```
