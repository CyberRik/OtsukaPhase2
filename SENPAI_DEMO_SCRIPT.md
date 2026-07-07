# Senpai — End-to-End Demo Script

A full walkthrough script for demoing Senpai: the AI sales co-pilot for reps ("junior") and their managers/coaches, plus the internal admin/ops portal. Written as a timestamped run-of-show for a ~25–30 minute live demo, with exact prompts/clicks and the talking point each beat is meant to prove.

**Before you start:**
- Backend running (`senpai/api/server.py`, FastAPI) and frontend running (`web/`, Next.js).
- Login page has one-click "fill demo creds" buttons: **junior / demo123** and **manager / demo123**.
- Have two browser windows/tabs ready: one for junior, one for manager (or use two profiles so you can flip between personas without logging out/in on stage).
- Good demo deal IDs (real seed data, deliberately at-risk so the coaching/health story is visible):
  - **D001** — 有限会社村田印刷 ディスプレイ案件 (rank 3_A, rep R12)
  - **D005** — 株式会社松田サービス セキュリティ案件 (rank 2_A+, rep R05)
  - **D010** — 株式会社平和システム プレゼン機器案件 (rank 2_A+, rep R14)
- Have one real company URL ready for the `/intel` live-crawl beat (any public vendor/customer site works — the crawler just needs a reachable domain).
- Have one small text/PDF file ready to attach in chat (e.g. a fake meeting note or a one-pager).

---

## 0:00–1:30 — Framing (no clicking yet)

**Say:** "Senpai is a sales co-pilot built for how Japanese enterprise sales teams actually work — a junior rep who needs a senpai (先輩/senior mentor) at 11pm before a big call, and a manager who needs to coach 10+ reps without reading every note personally. Everything you'll see is one FastAPI backend and one Next.js frontend — no separate demo mode. All tool calls are real: real CRM lookups, real web search, real document generation, real deal-health scoring. I'll show it end to end: junior rep workflow, tool-calling and grounding, document generation, a live web crawl, a training simulator, the manager coaching loop, and the admin ops portal."

---

## 1:30–3:00 — Login & language toggle

1. Open the login page, select **Junior**, click the pre-filled demo creds (`junior` / `demo123`), log in.
2. Point out the **JA/EN toggle** in the header (`web/components/site/lang-toggle.tsx`) — click it once to flip the whole product to English, click again back to Japanese.

**Say:** "The product is fully bilingual — not just labels, the coaching content, tool names, and slash command picker all localize live. We default to Japanese since that's the primary market."

---

## 3:00–6:00 — Natural-language tool calling (no slash command)

In the main chat composer, type a plain question — **no slash command** — to show the model deciding which tool to call on its own:

> **Prompt:** `アクメ商事の案件どうなってる？最新のステータス教えて`
> *("How's the Acme deal going? Give me the latest status.")* — substitute a real seeded customer name if "アクメ商事" isn't in seed data; e.g. use 富士商事 (C01) or 豊田工業 (C02).

**While it streams, click to expand the tool-call row** in the assistant message (the collapsible card with the Database icon). Show:
- The **args** it passed (customer name/id resolved).
- The **internal: grounded** badge — this is real CRM data, not a hallucination.
- The **execution timeline** if multiple tools fire (e.g. deal lookup → health score).

**Say:** "There's no slash command here — the system prompt instructs the model to always call a tool rather than answer from memory whenever the answer depends on real data. What you're looking at is `query_spr` and `score_deal_health` firing automatically. Every tool call renders as an inspectable card — query, args, and result — so a rep can verify what Senpai actually looked up."

Follow up with a risk-oriented prompt to show another tool:

> **Prompt:** `今リスクの高い案件ってどれ？`
> *("Which deals are high-risk right now?")*

This should fire `list_at_risk_deals` — point out **D005** or **D010** appearing with a flagged reason.

---

## 6:00 (bonus beat) — THE MEGA-PROMPT: one turn, 15–20+ tool calls

This is the beat to run when judges want proof this isn't a scripted 1-tool-per-message demo. It's not a trick — the backend genuinely supports up to **30 rounds of tool calling per turn** (`MAX_TOOL_ROUNDS`, `senpai/config.py`), and round 0 has a **deterministic fan-out expander** (`_audit_gather_calls` / `_multi_entity_gather_calls` in `senpai/llm/client.py`) that turns one prompt naming multiple reps/deals/customers into a real batch of grounded lookups before the model even starts reasoning. Say this explicitly to the judges: *"This isn't one call dressed up — watch the tool count."*

There are two ways to trigger the fan-out. Use whichever fits the persona you're in. **Use straight ASCII quotes `'...'` exactly as written below** — the parser matches on literal `'` / `"` characters, not Japanese fullwidth quotes.

### A. Manager persona — "quarterly pipeline audit" (numbered list + audit keyword → deterministic fan-out)

This exact prompt was traced line-by-line against `_audit_gather_calls` (`senpai/llm/client.py:485`) and its four sub-parsers — every deterministic call below is guaranteed to fire from round 0 alone, before the model reasons at all:

> **Prompt (paste exactly, keep the straight quotes):**
> ```
> 四半期パイプライン監査をお願いします。以下を確認してください:
> 1. 伊藤翔(R05)、松本千尋(R14)、山田彩(R12)の担当案件の最新ステータスとヘルススコア
> 2. 株式会社松田サービス、株式会社平和システム、有限会社村田印刷の日報を確認し、予算削減の言及がないか検索
> 3. 'セキュリティ'案件の一覧
> 4. 'OA機器'案件の一覧
> 5. 'PC周辺機器'案件の一覧
> 6. プレイブックとシナリオ: 'セキュリティ商談における反論対応'を検索
> 7. 業界の最新動向もWebで確認して、リスクの高い案件には次のアクションを提案して
> ```

**What's guaranteed to fire in round 0 (13 calls, verified against the regex logic):**
- Line 1 → `_REP_ID_RE` matches R05/R14/R12 → **3× `query_spr`** (one per rep)
- Line 2 → the three customer names are matched verbatim against seed data by `_mentioned_customers` → **3× `query_spr`** (one per customer); the line also contains "日報" + "予算削減", which trips the note-search branch → **3× `search_notes`** (one per customer)
- Lines 3–5 → each is its own bulleted line with a quoted category and the keyword "案件", none of the exclusion words ("status"/"類似"/"product code") → **3× `find_deals`** (security / OA equipment / PC peripherals)
- Line 6 → contains "プレイブック"/"シナリオ" plus a quoted query → **1× `retrieve_playbook`**

That's already 13 tool calls in a single scheduler batch, before the model has generated a single token. **Line 7 is deliberately left for the model** — asking for a live web check and next-action recommendations that aren't part of the deterministic gather forces at least one round of organic reasoning on top, typically adding `web_search`/`web_research`, `score_deal_health` (health scores were asked for in line 1 but the deterministic path only pulls records, not health — the model has to close that gap itself), and `advise_solutions` or `route_to_expert` for the recommendation — pushing the realistic total to **16–20 tool calls** in one turn.

**Say while the timeline fills:** "Thirteen of these calls happen in a single parallel batch, in the same round — before the model has even started 'thinking.' Then it picks up the parts of the ask that need judgment — checking the web, scoring risk, recommending next actions — on top. That's the split we designed for: deterministic, auditable gathers for anything mechanical, model reasoning reserved for anything that actually needs it."

### B. Either persona — multi-deal comparison (named IDs → deterministic fan-out)

Simpler to say out loud, still hits the expander (`_multi_entity_gather_calls` triggers on ≥2 named deal IDs):

> **Prompt:** `D001、D005、D010を比較して。それぞれのヘルススコア、リスク要因、類似の過去案件、関連製品を調べて、来週のフォローアップ会議もカレンダーに仮押さえして`
> *("Compare D001, D005, and D010 — health score, risk factors, similar past deals, and related products for each, and also tentatively hold a follow-up meeting on the calendar for next week.")*

**What fires:** `score_deal_health` ×3 + `query_spr` ×3 (one pair per deal, from the expander) → then the model layers on `find_similar_deals` ×3, `search_products` per product category, and finally `get_calendar` + `schedule_meeting` to close the loop with a real calendar action. This variant is the one to use if you also want to show **action-taking tools** (scheduling), not just read-only research, in the same mega-turn.

### C. "Show me everything" — research → decide → act → generate, in one message

The single best judge-facing prompt if you only get to run one: it chains read tools, a live web tool, an action tool, and a generation tool, so the tool-call list visibly spans every category in the system.

> **Prompt:** `D005について徹底的に調べて。案件情報とヘルススコア、類似の成約案件、関連プレイブック、そしてセキュリティ業界の最新動向をWebで確認したうえで、対応する提案書を作成して。あわせて顧客宛のフォローアップメールの下書きと、来週の商談の仮予定も作成して`
> *("Do a deep dive on D005 — deal info and health score, similar won deals, the relevant playbook, and check the web for the latest security-industry trends — then generate a matching proposal document. Also draft a follow-up email to the customer and tentatively schedule next week's meeting.")*

**What fires (roughly, in order):** `query_spr` → `score_deal_health` → `find_similar_deals` → `retrieve_playbook`/`search_knowledge` → `web_search`/`web_research` → `generate_proposal` (which itself internally re-calls `query_spr` + `web_search` for grounding, per `_gather_grounding` in `senpai/tools/impl.py`) → `draft_message` → `get_calendar` → `schedule_meeting`. That's 10-12 distinct tool *names*, several called more than once — a genuinely large, diverse tool-call graph from one message, ending with three tangible artifacts (a scored deal read, a downloadable proposal, and a drafted email) instead of just a wall of text.

**Say (for all three variants):** "Every one of these tool calls is inspectable — click any row in the timeline and you'll see the exact arguments and the exact result that came back, not a summary the model made up after the fact. We're not counting tool calls to impress you; the point is that a rep or manager could ask this exact question in plain language and get a fully-grounded, multi-source answer instead of switching between six different systems."

---

## 6:00–9:00 — Local file capability

1. Click the **paperclip icon** in the composer.
2. Attach the prepared text/PDF (a meeting note or one-pager).
3. Note the **pending chip** that appears above the composer showing the extracted filename.
4. Send a prompt referencing it:

> **Prompt:** `この資料の内容を要約して、次のアクションを3つ提案して`
> *("Summarize this document and suggest 3 next actions.")*

**Say:** "Senpai extracts text from PDF, DOCX, PPTX, XLSX, or plain text on attach — this isn't just OCR-and-dump, it's fed as grounded context into the same tool-calling loop. There's also a dedicated workspace file system underneath — `search_workspace_documents` and `edit_workspace_document` — so Senpai can pull up documents a rep uploaded days ago without re-attaching them, and even edit/move files inside a sandboxed workspace folder."

*(Optional deeper cut: mention `senpai/ingestion/pipeline.py` handles meeting **audio and photos** too — `process_audio`/`process_image` — turning a voice memo or a whiteboard photo into a structured activity report. Only do this if you have a prepped audio/image asset; otherwise just narrate it.)*

---

## 9:00–12:00 — Slash commands: `/review`, `/account`, `/research`

Type `/` alone in the composer to pop the **slash command picker** — narrate the full list (`/review`, `/account`, `/research`, `/crew`, `/team`, `/intel`) before picking one.

**`/review`** — paste a rough meeting note:

> **Prompt:** `/review 本日訪問。先方は予算に懸念あり。決裁者は未確認。競合A社も提案中とのこと。`

**Say:** "This is the senior's read on a daily report — Senpai flags what's missing (no confirmed decision-maker, competitor present) using the same deterministic coaching-issue engine the manager's dashboard uses later."

**`/account`** — pull a customer brief:

> **Prompt:** `/account 富士商事`

**`/research`** — cross-search internal + web:

> **Prompt:** `/research 複合機業界の最新トレンドと主要競合`
> *("Latest trends and key competitors in the copier/MFP industry")*

**Say:** "Research blends internal knowledge-base retrieval — our own playbooks and won-deal cases — with a live web search, and gives you a single source ledger showing which claims came from where."

---

## 12:00–16:00 — `/crew`: multi-agent deal analysis

> **Prompt:** `/crew D005`

Watch the **Execution Timeline** in `crew-turn.tsx` — Researcher → Coach → Strategist phases animate, then auto-collapse into a final brief.

**Say:** "This is three agents working one deal in sequence — a Researcher agent pulling account/product context, a Coach agent applying our deal-health rules, and a Strategist synthesizing next steps. It's not just one long prompt; you can watch each phase execute and see what each agent contributed before the final brief renders."

*(If time allows, show `/team` — manager-only — which runs one analyst per rep across the whole team plus a team-lead action list. Best done later in the manager segment instead, to avoid persona-switching mid-flow.)*

---

## 16:00–19:00 — `/intel`: live web crawl

> **Prompt:** `/intel <prepared company URL>`

**Narrate while it runs** — this is the most visually impressive tool-call, so let it breathe:

**Say:** "This is a real headless browser — Playwright — crawling the target site live, not a cached search result. Watch the feed: current URL, screenshot frames, and running counts of products/news/PDFs it's found. It'll visit up to six pages on this site before synthesizing a pre-call brief. This is exactly what a rep does manually for twenty minutes before a first meeting — Senpai does it in the time it takes to make coffee."

Once done, open the generated pre-call brief and note it's downloadable.

---

## 19:00–23:00 — Document generation (PPTX / DOCX / proposal / ringisho)

> **Prompt:** `D005の提案書を作成して` *("Create a proposal for D005")*

**Say while it generates:** "No confirmation prompt — the system is instructed to generate immediately once it has a deal to ground on. Under the hood this renders one HTML deck first, exports a pixel-perfect PDF via headless Chromium, then measures every text box in that HTML and bakes matching editable text boxes into a PPTX over a screenshot background layer. So what downloads is a real, editable PowerPoint — not a flattened image — plus a PDF and the HTML source, generated from the exact same layout."

Click the **download chip** that appears in the tool-call card (and note it's also promoted to the top-level answer) to actually open the PPTX and show it's editable.

Optionally also show:

> **Prompt:** `この案件の稟議書を作って` *("Draft the ringisho / internal approval doc for this deal")*

**Say:** "稟議書 — the internal approval document — is a distinctly Japanese enterprise artifact; Senpai generates it the same way, grounded on real deal data."

---

## 23:00–27:00 — Training Simulation: 稟議攻略トレーニング・シアター (Ringi Boardroom)

Navigate to `/junior/training/ringi`.

1. Pick an at-risk deal from the dropdown (**D005**, **D001**, or **D010**).
2. Click **稟議シミュレーション開始** ("Run simulation").
3. Narrate as it streams: personas (課長/Kacho, 部長/Bucho, 社長/Shacho) speak in turn around the boardroom ring, the **approval gauge** ticks up/down live based on their objections, a live transcript feed shows each line, and the **Senpai HUD** surfaces coaching whispers tied back to the real flagged issue.
4. After it resolves (likely low approval, given a real at-risk deal), click the **Playbook Intervention** card, apply the suggested fix, and **re-run** — watch the approval gauge recover green.

**Say:** "This is a rehearsal environment for 稟議 — Japan's internal consensus/approval process, which is often the real bottleneck in enterprise deals, not the customer meeting itself. It's not scripted theater — the objections each persona raises are generated from the same deterministic deal-health engine you saw in `/crew` and the coaching dashboard, so if you fix the underlying issue (say, an unconfirmed decision-maker) in the real data, the simulation reflects that the next time you run it. A rep can practice defending a deal to a skeptical department head before they ever do it for real."

---

## 27:00–33:00 — Manager persona: coaching loop

Switch to the manager tab/window, log in (`manager` / `demo123`).

1. **`/team`** in chat: `/team` — one analyst per rep across the whole team plus a team-lead action list, same crew-turn UI as `/crew` but team-scoped.
2. Navigate to the **Coaching** tab.
3. **Team Roster** — show the manager's adopted reps.
4. **Needs Coaching** tab — flagged deals/reps surfaced automatically (same issue-detection engine as `/review` and the Ringi simulation).
5. **Confidence vs Reality** tab — a rep's self-reported confidence vs. what the data actually shows.
6. **Reps** tab → click into one rep row → expand to show: weaknesses, the specific principle/case Senpai recommends, a suggested action, a progress trend chart, and the **coaching thread** (chat history between manager and rep on that issue).

**Say:** "This is the same deterministic 7-issue coaching engine running everywhere in the product — `/review` used it on a single note, the Ringi simulator used it to script objections, and here it's aggregated across an entire team so a manager doesn't have to read every daily report to know who needs help and on what. When a manager opens a coaching thread and the rep resolves the flagged issue, `coach/progress.py` tracks that as an 'acted-on' signal over time — so this becomes a longitudinal record of whether coaching actually worked, not just a one-time note."

---

## 33:00–38:00 — Admin / ops portal

Navigate directly to `/admin` (no login gate — internal ops surface by design).

Walk the nav in order:
1. **Overview** — system snapshot.
2. **People** — every rep/manager in the system.
3. **Org & Assignments** — click into a rep, **reassign them to a different manager** live (`POST /api/admin/reps/{id}/reassign`) to show org changes take effect immediately.
4. **Activity** — the system-wide feed: every coaching-thread message and daily report across the whole org, newest first.
5. **LLM Usage** — token usage/cost broken down by model and prompt label — directly answers "what is this costing us."
6. **Pipeline Health** — win rate by segment.
7. **System Status** — LLM on/off, pinned demo date, retrieval mode, model endpoints.
8. **Visualization** — the GraphRAG showcase: network graph of deal/customer relationships, community detection, a live-retrieval view, and a "vs. traditional search" comparison.

**Say:** "This is deliberately an internal English-only ops surface, not a rep-facing product — hence no login gate and no localization. It's where an admin manages org structure, watches spend, and — this last part is the one I'd linger on — actually see the GraphRAG relationship graph and community detection that powers `search_knowledge` and account intelligence under the hood. Most vendors treat retrieval as a black box; we expose it."

---

## 38:00–40:00 — Close

**Say:** "To recap what you just saw in one flow: a rep asks a plain-language question and gets grounded, inspectable tool calls — not a black box. They attach a real file and get it summarized in context. They pull account intelligence, cross-reference the open web, run a live browser crawl for a pre-call brief, and generate an editable proposal deck, all from natural language, no manual template work. They rehearse the hardest part of enterprise sales — internal approval — in a simulator built on their real deal data. And on the other side, a manager coaches an entire team off the same deterministic signals, with full traceability into whether coaching actually changed behavior over time. Admin ties it all together with cost, org, and retrieval transparency. One backend, one set of tools, every surface grounded in the same real data."

---

## Appendix: quick-reference command list

| Command | Purpose | Example |
|---|---|---|
| *(plain text)* | Model auto-selects the right tool | `アクメ商事の案件どうなってる？` |
| `/review <note>` | Senior's structured read on a daily report | `/review 本日訪問。予算懸念あり。` |
| `/account <name>` | Customer brief from internal records | `/account 富士商事` |
| `/research <topic>` | Internal + web cross-search with source ledger | `/research 複合機業界の最新トレンド` |
| `/crew <deal>` | Researcher + Coach + Strategist analyze one deal | `/crew D005` |
| `/team` | Same crew analysis, one pass per rep (manager-only) | `/team` |
| `/intel <url>` | Live headless-browser crawl → pre-call brief | `/intel https://example.com` |
| *(natural language)* | Document generation (proposal/ringisho/pptx/docx) | `D005の提案書を作成して` |

## Appendix: mega-prompts (15–20+ tool calls in one turn)

Keep these ready to paste if a judge asks "how many tools can it actually call." Mechanism: `MAX_TOOL_ROUNDS=30` per turn (`senpai/config.py`) + deterministic round-0 fan-out expanders in `senpai/llm/client.py` (`_audit_gather_calls`, `_multi_entity_gather_calls`) that turn a list of named reps/deals/customers into a batch of real grounded lookups before the model even starts reasoning.

1. **Quarterly audit fan-out (manager persona) — 13 guaranteed + ~5 organic tool calls:**
   ```
   四半期パイプライン監査をお願いします。以下を確認してください:
   1. 伊藤翔(R05)、松本千尋(R14)、山田彩(R12)の担当案件の最新ステータスとヘルススコア
   2. 株式会社松田サービス、株式会社平和システム、有限会社村田印刷の日報を確認し、予算削減の言及がないか検索
   3. 'セキュリティ'案件の一覧
   4. 'OA機器'案件の一覧
   5. 'PC周辺機器'案件の一覧
   6. プレイブックとシナリオ: 'セキュリティ商談における反論対応'を検索
   7. 業界の最新動向もWebで確認して、リスクの高い案件には次のアクションを提案して
   ```
   (keep the straight `'` quotes on lines 3–6 exactly as written — the parser matches literal ASCII quotes)

2. **Multi-deal comparison + calendar action (either persona):**
   `D001、D005、D010を比較して。それぞれのヘルススコア、リスク要因、類似の過去案件、関連製品を調べて、来週のフォローアップ会議もカレンダーに仮押さえして`

3. **"Show me everything" — research → decide → act → generate (best single judge-facing prompt):**
   `D005について徹底的に調べて。案件情報とヘルススコア、類似の成約案件、関連プレイブック、そしてセキュリティ業界の最新動向をWebで確認したうえで、対応する提案書を作成して。あわせて顧客宛のフォローアップメールの下書きと、来週の商談の仮予定も作成して`

See the "THE MEGA-PROMPT" section above (after the 6:00 tool-calling beat) for exactly which tools each one fires and the talking point to say while the timeline fills up.

## Appendix: seed data cheat sheet

- Demo logins: `junior`/`demo123`, `manager`/`demo123`.
- At-risk demo deals: **D001** (村田印刷), **D005** (松田サービス), **D010** (平和システム).
- Sample customers for `/account`: 富士商事 (C01), 豊田工業 (C02).
- Admin portal: `/admin` — no auth gate, English-only by design.
- Training simulator: `/junior/training/ringi`.
