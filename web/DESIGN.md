# Senpai — Frontend Design Specification

Production-quality frontend presenting Senpai as a **knowledge-transfer and
onboarding platform** for salespeople. This document is the design system + the
per-page spec + the component hierarchy. The implementation lives in this `web/`
directory and is built against the existing engines via the FastAPI bridge
(`senpai/api/server.py`) — **no backend logic changed.**

---

## 1. Design intent

**Avoid generic AI-chatbot aesthetics.** No bubble streams, no sparkle-purple
gradients, no "Ask me anything." The product is a *senior rep's reasoning made
legible* — so the visual language is an **intelligence dossier**: warm paper,
sumi ink, hairline rules, generous whitespace, an editorial serif for authority.

Four things are always visually first-class, because they are the product's moat:

| Emphasis | How it shows up |
|---|---|
| **Senior reasoning** | The Coach output is six labelled *lenses*, not prose. Each is "what a senior would notice / ask," framed as a thinking pattern. |
| **Provenance** | Every principle renders the **verbatim interview sentence** it rests on, with a source chip (`I01`/`I02`) in vermilion. |
| **Confidence** | A computed, never-authored badge (high/medium/low/unverified) with the rule it was derived from in the tooltip. |
| **Knowledge transfer** | Home leads with the three-layer trust model (Source → Principle → Item) and the rule "GenAI may only derive down, never invent up." |

### Tokens (`app/globals.css`, `tailwind.config.ts`)

- **Palette** — paper `40 33% 98%`, sumi ink `60 6% 11%`, ai-indigo primary
  `224 32% 27%`, warm-sand accent, a single **vermilion seal** `9 62% 47%` for
  provenance + brand. Traffic-light colour is *reserved* for deal health; the
  confidence scale has its own restrained colours.
- **Type** — Spectral (serif display + headings), Inter (sans body/UI),
  Noto Sans JP (all Japanese content). Tiny uppercase letter-spaced `.eyebrow`
  labels are the spine of the dossier look.
- **Surfaces** — `card-surface` (hairline border + soft `shadow-card`),
  `texture-grid` (faint engineering-paper grid, masked) for hero/empty states,
  `.quote-jp` (serif, vermilion ruled margin) for verbatim quotes.

---

## 2. Information architecture

```
Sidebar (persistent)        Brand seal 先 · Platform nav · "The promise" footer
  /            Home          What Senpai is + trust model + entry points
  /coach       Review Coach  Paste note → six lenses of reasoning
  /knowledge   Explorer      Principles · provenance · derived items
  /dashboard   Dashboard     Deal-health · reliability flags · drill-down
```

Every page = `PageHeader` (eyebrow + serif H1 + lead) over a content region. A
`LiveBadge` ("Live engine" / "Seed snapshot") tells the truth about data source.

---

## 3. Per-page specification

### 3.1 Home (`/`)

- **Layout** — hero (badge → serif H1 → lead → two CTAs over a masked grid);
  four-up stat band; three-layer trust model with connective arrows; three
  product cards; a provenance teaser pairing a claim with its verbatim quote.
- **Components** — `Button` (seal + outline), stat cells, `LAYERS` cards,
  feature `Link` cards, `ConfidenceBadge` legend, `SourceChip`, `.quote-jp`.
- **Visual hierarchy** — the H1 promise is the loudest object; the trust model is
  the argument; the stat band ("2 interviews → 11 principles → 4 items → 49
  deals") is the proof.
- **Empty state** — none (static narrative).
- **Demo state** — stats pull live counts from the API; if offline they fall back
  to the real seed numbers, so the page is always populated.

### 3.2 Sales Review Coach (`/coach`)

- **Layout** — two columns. Left (sticky): a note "sheet" textarea, an optional
  *relate-to-a-deal* selector, the seal action, and example chips. Right: a
  persistent teaching banner + a 2-column grid of six **lens cards**.
- **Components** — `CoachConsole`, `LensCard` (icon + EN/JP heading + bulleted
  reasoning), `SeniorTip` (parses `先輩の知見(出典… / 確度…)` lines into a cited,
  confidence-badged card), `LiveBadge`, `Skeleton`.
- **User flow** — paste / pick an example → "このメモをコーチに見せる" → six lenses
  animate in. Optionally bind a deal so structured signals reinforce the text.
- **Visual hierarchy** — the teaching banner ("考え方の型 — not one right answer")
  sits above the output so the framing is unmissable; risks tone red, questions
  vermilion, next-moves green — the eye triages by lens.
- **Empty state** — never blank: on mount it auto-coaches the first example.
- **Demo state** — four curated examples each trip a different lens cluster
  (decision-maker, competitor, first-visit, decision-maker感触).

### 3.3 Knowledge Explorer (`/knowledge`)

- **Layout** — a source-corpus strip (2 interviews + instrument) above a
  master–detail: left = filterable principle list; right = selected principle
  with its **verbatim provenance** and the coaching items derived from it.
- **Components** — `KnowledgeExplorer`, `SourceStrip`, `Tabs` (all / approved /
  two-source), search, principle list buttons, `ProvenanceList` (verbatim
  `.quote-jp` + `SourceChip` + location), `ItemCard` (scenario + four facets +
  `ConfidenceBadge` + grounding pass), `Badge`.
- **User flow** — filter to "2名一致" (both seniors agree) → pick a principle →
  read the exact sentences → see the human-approved scenario it produced.
- **Visual hierarchy** — the principle statement is serif and large; the
  provenance quotes sit beneath a "Traceable to source" rule; confidence rides
  on every derived item.
- **Empty states** — no principles match the filter → quiet message; a principle
  with no approved items → an explainer that only human-gated items reach the
  Coach (turns an empty into a *feature* statement).
- **Demo state** — defaults the selection to a two-source principle (P008/P006/
  P001/P011) so the first thing a viewer sees is a high-confidence, fully-cited
  chain.

### 3.4 Manager Dashboard (`/dashboard`)

- **Layout** — rep filter + as-of date; four KPI cells; a stacked pipeline-health
  bar; a clickable deal table; a reliability-flags grid. Clicking a row opens a
  right-side **drill-down drawer**.
- **Components** — `DashboardView`, `Kpi`, `BandPill` / `BandDot` / `RiskMeter`,
  deal `table`, `DealDrawer` (`Dialog`) with signal breakdown, flags, notes.
- **User flow** — scan KPIs → spot red band / flag count → open a deal → read the
  signal-by-signal reasons (`+30 67日間連絡なし…`) that produced the score.
- **Visual hierarchy** — band colour is the loudest signal; the `optimism_mismatch`
  flag (rep says "high," health is red) is the executive money-shot.
- **Empty states** — rep with no deals → message; no flags for the selection →
  a green "all clear" panel (positive, not blank).
- **Demo state** — `SENPAI_TODAY=2026-06-16` pins scoring so bands are identical
  every run; offline it shows the representative seed slice and labels itself.

---

## 4. Component hierarchy

```
app/layout.tsx                     fonts, TooltipProvider, Sidebar shell, footer
 ├─ components/site/sidebar.tsx     Brand · nav · "promise" footer
 ├─ components/site/page-header.tsx eyebrow + serif H1 + lead
 └─ components/site/live-badge.tsx  live vs. seed-snapshot honesty

app/page.tsx (Home)                hero · stats · trust model · surfaces · teaser

app/coach/page.tsx
 └─ components/coach/coach-console.tsx
     └─ LensCard ─ SeniorTip ─ SourceChips · ConfidenceBadge

app/knowledge/page.tsx
 └─ components/knowledge/knowledge-explorer.tsx
     ├─ SourceStrip
     ├─ Tabs · search · principle list
     ├─ components/provenance.tsx (ProvenanceList → ProvenanceQuote)
     └─ ItemCard ─ ConfidenceBadge

app/dashboard/page.tsx
 └─ components/dashboard/dashboard-view.tsx
     ├─ Kpi · pipeline bar · deal table
     └─ components/dashboard/deal-drawer.tsx (Dialog) ─ RiskMeter · BandPill

shared primitives
 components/ui/*        button card badge separator tabs dialog tooltip
                        accordion textarea skeleton  (shadcn/Radix)
 components/confidence-badge.tsx · source-chip.tsx · provenance.tsx · band.tsx
 lib/{api,types,fixtures,utils}.ts
```

---

## 5. Data contract & resilience

`lib/api.ts` is typed against `senpai/api/server.py`. Every call has a fixture
fallback (`lib/fixtures.ts`, which holds the **real cited** knowledge data), so a
demo with no API running still renders real-shaped screens — and says so via
`LiveBadge`. Server Components fetch at request time (`force-dynamic`); the Coach
posts client-side. `NEXT_PUBLIC_API_BASE` points the client at the bridge.
