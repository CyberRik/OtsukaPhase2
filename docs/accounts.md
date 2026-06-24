# Account Intelligence

Deal health answers *"is **this opportunity** on track?"*. **Account
intelligence** answers the senior manager's question: *"is **this whole customer
relationship** healthy and growing?"*. It is a separate, deterministic engine
(`senpai/account/`) that rolls a customer's deals, activities, quotes and orders
into one grounded read — surfaced as the **Accounts** pages and the Workspace
`/account` skill.

> Everything here is **pure and deterministic** — every number traces to a store
> record, no LLM, no randomness. The LLM only writes a *commentary* layer over
> the already-computed package, under a strict no-invention contract.

---

## The engine (`senpai/account/`)

| Module | Produces | Notes |
|---|---|---|
| `health.py` | `account_health()` → 0–100 score + band + 8 dimensions | **Higher-is-better** (inverse of the deal risk score, so they're never confused) |
| `trajectory.py` | `relationship_trajectory()` → list of `Pattern` | Direction of the relationship (positive/risk/neutral), not just current state |
| `expansion.py` | `expansion_opportunities()` → list of `Opportunity` | Cross-sell / upsell / growth, grounded in catalog + environment |
| `summary.py` | `build_account_summary()` → `AccountSummary` | Orchestrates the three + headline aggregates |
| `context.py` | `build_account_context()` + `account_commentary_prompt()` | Renders the summary into a grounded text package for the LLM read |

### Account health — 8 weighted dimensions

`account_health(customer_id)` sums eight pure dimensions (weights sum to 100),
each returning `(points, max, reason)` with a human-readable Japanese reason:

| Dimension | Weight | Measures |
|---|---|---|
| `activity_trend` | 15 | recent-90d vs prior-90d activity ratio |
| `inactivity` | 10 | days since last activity (decays 14→90d) |
| `pipeline_progression` | 15 | open deals advanced vs slipped (by `order_rank`) |
| `win_rate` | 15 | won / (won+lost) closed deals |
| `quote_engagement` | 10 | recent quotes + quote→order conversion |
| `order_recency` | 15 | recency of last order + repeat-order count |
| `dm_access` | 10 | share of open deals with a decision-maker identified |
| `growth` | 10 | recent-180d vs prior-180d order revenue |

Band: **≥70 green** (healthy/strategic), **45–69 yellow** (watch), **<45 red**
(at risk). `AccountHealth.top_reasons(n)` returns the dimensions dragging the
score down most (lowest fraction of max) — these become the "weakest dimensions"
the commentary must explain.

### Relationship trajectory — direction detectors

`relationship_trajectory()` runs deterministic pattern matchers over the
account's aggregates, each emitting a `Pattern(id, label, evidence, polarity)`:

- **positive:** `repeat_purchasing`, `activity_increasing`, `expansion_potential`
- **risk:** `activity_declining`, `spend_declining`, `multiple_stalled`
  (≥2 open deals scoring red), `engaged_no_progress` (lots of contact, zero
  advancement/revenue), `loyal_dormant` (past wins but ≥60d silent)

Each pattern's `evidence` is a concrete string ("赤判定の進行中案件 2件: D012、D031")
so the UI and the LLM can refer to it by `[id]`.

### Expansion opportunities — three families

`expansion_opportunities()` is a rule engine over store records (the only
authored content is a category adjacency map and environment-trigger phrases):

1. **cross-sell** — gap categories *complementary* to something the account
   already owns (static `_COMPLEMENTS` adjacency over the 7 catalog majors).
2. **upsell** — environment upgrade triggers (`ADSL|更改検討|老朽`, `Windows 10|EOL`,
   `無線LAN|Wi-Fi`) matched against the customer's IT environment record.
3. **growth** — engaged account (≥2 open deals) with thin category coverage (≤2)
   → strategic-account flag.

Each `Opportunity(kind, target, rationale, evidence, confidence)` carries its own
grounding.

### The roll-up — `AccountSummary`

`build_account_summary(customer_id)` folds it all together: industry/size, active/
won/lost counts, open pipeline ¥, historical revenue ¥, a human activity-trend
line, last activity, recent quotes/orders, IT environment, the health dict, risk
signals (trajectory risks), expansion signals (opportunities + positive
patterns), and a single deterministic `recommended_focus` line derived from the
strongest signal — so there's always a sensible answer even with the LLM off.

---

## How it's fetched, with grounding

```
GET  /api/account/{customer_id}              → AccountSummary.to_dict()  (deterministic)
POST /api/account/{customer_id}/commentary   → SSE senior account read   (LLM over the package)
GET  /api/customers/resolve?q=…              → deterministic name→id resolution
POST /api/customers/smart-resolve            → deterministic + fuzzy + LLM-ranked resolution
```

**The grounding contract for the commentary** (`account/context.py`):

1. `build_account_context()` renders the `AccountSummary` into a compact text
   package where **every line traces to a record** — account header, deal counts,
   pipeline/revenue, health band + score + *weakest dimensions with reasons*,
   activity trend, **open deals with per-deal health band** (the deal↔account
   cross-link, so the read can name a specific stalled `D###`), recent orders/
   quotes, IT environment, risk signals `[id]`, expansion signals, and the
   deterministic recommended focus. If the customer doesn't exist the package is
   literally `"NO MATCHING ACCOUNT FOUND. Do not invent any account facts."`.
2. `account_commentary_prompt()` asks for a senior account-manager's read under
   four fixed headings (Account Reality / Single Deal vs Whole Account / The Real
   Risk: intent vs access / Recommended Focus). The rules force it to **ground
   every statement in the context, quote numbers exactly, refer to signals by
   `[id]`, and never invent** — and to keep it short (~120–170 words).
3. The endpoint streams with **reasoning disabled** (`no_think=True`) and is
   **pinned to the primary endpoint** (`allow_fallback=False`) — an account read
   should never silently come from a different model. On any failure it emits
   `unavailable` and the UI keeps the deterministic summary.

See [`resolution_and_routing.md`](resolution_and_routing.md) for the resolution
cascade and the reasoning router in full.

---

## Workspace continuity

The `/account` skill in the Workspace calls `/api/customers/resolve` to turn a
typed name into a `customer_id`, then the commentary endpoint with the shared
`conversation_id`. That call **seeds chat focus** (`_seed_chat_focus`): pulling an
account brief puts that customer "in focus" for the thread, so a later bare
follow-up ("what's their biggest risk?") stays scoped to it without re-typing the
name. The brief renders as an immutable `account_brief` **artifact** (see
[`workspace.md`](workspace.md)).

---

## The front end (`web/components/account/`)

| File | Route | What it does |
|---|---|---|
| `accounts-index.tsx` | `/{role}/accounts` | Discoverability surface — rolls the open-deal pipeline up by customer (worst band, open count, pipeline ¥) entirely from the existing dashboard payload, sorted by pipeline, each drilling into the account view. No extra backend. |
| `account-view.tsx` | `/{role}/accounts/[id]` | The full Account Intelligence page — fetches `api.account(id)` + dashboard, renders the 8 health dimensions, risk/expansion signals, recent quotes/orders, IT environment, open-deal drawer, and **streams the senior account read** via `accountCommentaryStream`. |

Both are role-aware (`junior` | `manager`) and share the same components; the
manager routes (`web/app/manager/accounts/...`) mount the identical views.

---

## Why it's credible

- **Two distinct scores, never confused.** Account health is higher-is-better;
  deal risk is lower-is-better. The doc strings and the inverse scale make the
  difference explicit.
- **Single tuning surface.** All eight dimension weights are module-level
  constants summing to 100 — health is auditable and re-weightable in one place.
- **Deal↔account cross-link.** The context package lists each open deal with its
  own health band, so the read can say "the account is healthy *but* D012 is
  stalling" — the exact senior insight a flat summary misses.
- **Grounded fallback.** Every layer degrades to the deterministic
  `recommended_focus` / summary if the LLM is unavailable.
