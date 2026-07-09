# Senpai — Content Reservoir for Supplementary Material

---

## 1. Positioning

**Senpai** — a **MULTIMODAL, HIGHLY AGENTIC, DETERMINISTIC-FIRST, SELF-HOSTED** AI sales co-pilot that gives every junior rep a senior mentor on demand, and every manager a real-time, evidence-based coaching lens — grounded entirely in Otsuka Shokai's own deal data, product catalog, sales process, and the captured judgment of its own senior reps.

One-line pitch: *"Senpai doesn't replace the senpai-kohai (先輩-後輩) relationship that makes Japanese sales teams work — it scales it."*

The three promises a manager cares about, up front:
- **決定論ファースト (deterministic-first).** Every number is computed in plain, auditable code *before* any AI sees it. The AI translates verified numbers into natural language — it is never the source of the number.
- **ハルシネーションを出さない (no hallucination, by construction).** Multiple independent grounding gates and citation firewalls mean an AI narrative that doesn't match the underlying data is rejected before it reaches a rep.
- **自社データ主権 (your data stays yours).** The reasoning model is a fine-tuned model **served on hardware you control** — customer, deal, and coaching data is never sent to a third-party AI API.

---

## 2. The problem this solves

- A junior rep needs a senior's judgment at 11pm before a big call tomorrow. A human senpai's time doesn't scale past a handful of kohai.
- The real bottleneck in enterprise sales in Japan is frequently not the customer meeting — it's internal consensus-building (稟議, ringi). This is a distinctly Japanese sales-process problem that generic, Western-built sales AI tools don't model at all.
- A sales manager responsible for a full team cannot manually read every daily report from every rep and still catch the one that's quietly going off the rails.
- Decades of product knowledge and winning-deal patterns live in senior reps' heads — hard to transfer, harder to scale, easy to lose on attrition/retirement.
- Enterprise AI tools are frequently black boxes; a company whose brand is built on trust and reliability cannot adopt an AI system that can't show its work, or that ships its customers' data off to an external vendor's API.

---

## 3. Core product capabilities (rep + manager facing)

### 3.1 Agentic tool-calling engine
- **38 distinct tools** spanning CRM/deal lookup, product catalog, quoting, communications, calendar, document generation, web research, and workspace file management. All tested and working correctly.
- **MULTIMODAL** inputs accepted — real-time TTS in the chat input, and any file uploaded via the attach button.
- **HIGHLY AGENTIC:** a single conversation turn can chain **up to 30 rounds** of tool calls — the system is architected for genuinely long, multi-step reasoning chains, not single-shot Q&A.
- Every tool call is rendered in the UI as an inspectable card: exact query, exact arguments, exact result — a rep or manager can verify precisely what Senpai looked up, not just trust a generated summary. This is **radical transparency by construction**.
- No slash command is required — natural language alone ("アクメ商事の案件どうなってる？") triggers the right tool automatically, in Japanese or English.
- **GROUNDED IN REAL SPR DATA (mock dataset), NO HALLUCINATIONS** — guardrails enforce this at every step.

### 3.2 Local file & knowledge retrieval (RAG)
- Ingests PDF, DOCX, PPTX, XLSX, TXT, and Markdown directly from chat — text extraction feeds straight into the grounded tool-calling loop, not a black-box summarizer.
- A dedicated **sandboxed workspace file system** lets Senpai search, read, edit, and move documents a rep uploaded days ago, without re-attaching them.
- Backed by a **hybrid retrieval engine**: BM25 keyword search (Japanese-aware, POS-filtered tokenization) fused with multilingual dense embeddings via **reciprocal rank fusion** — with a 3-tier graceful degradation path (dense+BM25 → BM25-only → keyword substring) so retrieval never goes fully dark, even if an embedding service is unavailable. The vector index is pre-built offline, so query-time retrieval needs no GPU.

### 3.3 Live web research
- Two distinct web tools: a fast **web search** (Tavily-backed) for quick facts, and a genuine **multi-page crawl** using a real headless browser (Playwright) — visiting up to **5 sites, up to 3 pages each** per request, then synthesizing a cited answer.
- The `/intel` flow streams a single-site crawl **live** — real live scraping, current URL, and running counts of products/news/PDFs discovered (up to **12 pages** deep), rendered in the browser as it happens. This is not a cached search result; it's an actual browser session a judge can watch execute in real time.
- Only the search query leaves the building — customer and deal data never do.

### 3.4 Document generation pipeline
- Natural-language triggers generate a **提案書 (proposal)**, **稟議書 (ringisho)**, a **Word document (DOCX)**, or a general slide deck — no confirmation dialog; the system generates immediately once grounded on real data.
- One HTML deck is rendered first; a headless Chromium instance exports a pixel-perfect PDF, then measures every text box in that same HTML to bake matching, genuinely **editable text boxes into a real PPTX** over a decorative screenshot background — not a flattened image pretending to be a slide. **One render → three formats (PPTX + PDF + HTML).**
- Document generation is itself internally grounded — it re-calls the CRM lookup and web search tools as part of its own execution, so even a "just make me a deck" request is fact-checked against real data before it renders.

### 3.5 Multi-agent deal & team analysis
- `/crew <deal>` — three agents (Researcher, Coach, Strategist) analyze one deal in sequence, with a visible execution timeline showing each phase before the final brief renders.
- `/team` (manager-only) — the same three-agent analysis fanned out across an entire team, plus a consolidated team-lead action list, in one request.

### 3.6 Ringi Boardroom — a training simulator built for a uniquely Japanese sales problem
- A rep picks a real, at-risk deal and rehearses the internal 稟議 approval process against three escalating personas — 課長 (section chief), 部長 (department head), 社長 (president) — each raising objections generated from the deal's actual, real flagged issues, not scripted dialogue.
- A live approval gauge ticks in real time as the rehearsal proceeds; a **"Senpai HUD"** surfaces coaching whispers tied directly back to the underlying data.
- After a failed run, the rep applies a suggested intervention and **re-runs the exact same simulation** — because objections are generated from real computed deal state, fixing the underlying issue visibly changes the outcome, closing the loop between coaching advice and consequence.
- This is, to our knowledge, a category of sales-training tool that does not exist in mainstream Western sales-enablement software — it is built specifically around the way enterprise sales actually gets approved inside a Japanese company.

### 3.7 Manager coaching loop
- A **deterministic (not LLM-guessed) issue-detection engine** flags **7 distinct coaching issue types** per rep — confidence/reality mismatch, missing decision-maker, inactivity, premature discounting, repeated unresolved issues, weak discovery, incomplete reporting.
- A **"Needs Coaching" queue** surfaces flagged reps automatically; a **"Confidence vs. Reality"** view compares a rep's self-assessment against what the data actually shows.
- Every flagged issue can be escalated into a coaching thread (a persistent chat between manager and rep); a **longitudinal progress tracker** replays the deterministic engine as-of each past period to measure whether a rep's flagged-issue rate actually declined after a coaching conversation — a genuine "did coaching work" signal over time, not a one-off note.

### 3.8 Coaching Explainability — "Why did Senpai recommend this?"
- Every coaching recommendation can be opened into a grounded, four-part explanation: **① Trigger Conditions** (which rule fired and what data matched it), **② Supporting Evidence** (the actual field values behind the trigger), **③ Similar Historical Cases** (real closed deals with the same pattern), and **④ Outcome Statistics** (win/loss rates computed from real data only).
- **Hard grounding rule:** every statistic is computed from real closed deals; when fewer than the minimum sample of matching deals exist, the system says *"insufficient data"* rather than inventing a misleading percentage.
- This turns coaching from an opaque nudge into an **auditable, evidence-backed argument** a manager can defend to the rep — exactly the standard of proof an Otsuka trust review would demand.

### 3.9 Similar Past Cases — teaching through real organizational experience
- Given a junior's note, Senpai surfaces a few **real past deals (won and lost)** whose situation rhymes with the current one — each tagged with its outcome and the validated senior principle it illustrates.
- This is **case-based reasoning grounded in the company's own history**: the "lesson" of each case is always an existing, interview-traceable principle, never a synthesized claim. New reps learn from what actually happened inside Otsuka, not from generic best-practice boilerplate.

### 3.10 Validated Knowledge Pipeline — captured senior judgment, provenance-tracked
- A structured pipeline turns **real senior-rep interviews and surveys** into a library of **validated sales principles (P001–P011+)**, each one human-authored and backed by exact citation spans from the source transcript.
- GenAI may *expand* a principle into concrete coaching guidance, but every generated item must pass a **grounding gate** and then a **human review gate** (draft → approved / needs-edit / rejected) before any junior ever sees it. Off-principle or hallucinated items are rejected and never shown.
- **Confidence is computed, never authored** — an item's confidence is re-derived from how well-sourced its backing principle is at the moment of approval, so it can't be inflated by hand. Every state transition records who approved it and when, so **provenance survives**.
- Managers/trainers get a **Knowledge Explorer** and an "add principle" flow — the institution's best judgment becomes a living, auditable, reusable asset instead of tribal knowledge locked in senior reps' heads.

### 3.11 Admin / operations portal
- **11 distinct admin views**: Overview, People, Org & Assignments, Activity, LLM Usage, Pipeline Health, System Status, and a 4-view Visualization suite (Network graph, Communities, Live retrieval, GraphRAG-vs-traditional comparison).
- Org reassignment (moving a rep to a different manager) takes effect live, with an immediate API-backed update — not a mocked control.
- A real, per-call **token/cost usage ledger** — every LLM invocation logged with real-vs-estimated token counts, rolled up per day, per model, per prompt label, feeding a live spend dashboard with a configurable cost-per-1K-token rate.

### 3.12 Fully bilingual, day one
- Switch instantly between Japanese and English with one click, no page reload — deployable to a Japanese-first workforce today, equally usable by international team members.

### 3.13 Account intelligence & strategic planning
- A dedicated **account plan view** (separate pages for rep and manager) showing account health, growth trajectory, and concrete expansion opportunities for any customer — not buried in chat, a standalone strategic workspace.
- Powered by a real **deterministic engine** (health / trajectory / expansion / strategy scoring modules) plus an on-demand, grounded AI commentary layer.
- The same expansion-opportunity signals feed directly into the recommendation engine below — one computed account picture, reused everywhere it's relevant, not recomputed ad hoc per feature.
- Advice is **region-aware (関東 Kanto vs 関西 Kansai)** and **deal-size-aware (money)** — Senpai adapts its guidance to where the customer sits and how big the deal is.

### 3.14 Solution recommendation engine — a second, independent grounding firewall
- Goes meaningfully beyond a keyword/category filter: candidate solutions are generated from **two signal layers** (category/industry match plus real account-expansion signals) and scored with a confidence-weighted ranking, *before* any AI text is generated.
- The explanation step is **citation-firewalled**: the model may only narrate the closed, pre-ranked candidate list, and any citation it produces is checked against the allowed set and stripped if it doesn't verify. This is a second, independently-implemented instance of the same anti-hallucination pattern used in the GraphRAG grounding gate.

### 3.15 Instant, catalog-grounded quoting
- Generates a real structured price quote — line items resolved against actual product-catalog pricing, with computed subtotal, discount, tax, and grand total — not a fabricated number.
- Explicitly and unambiguously labeled as a draft that is never auto-sent or persisted without a human in the loop.

### 3.16 Communication & scheduling actions
- `draft_message` and email drafting are available.
- Meeting scheduling goes a step further: it integrates with the **real Google Calendar API** to actually book a calendar hold.

### 3.17 "Know when to hand off" — the route-to-expert safety valve
- When a question is outside what Senpai should answer alone, `route_to_expert` doesn't just say "ask someone senior" — it scores every senior/expert rep in the org against the actual question, using real specialty-tag overlap, keyword matching, and a top-performer boost, and names the single best-matched real internal expert plus a draft outreach message.
- This is a concrete answer to the natural enterprise objection *"what happens when the AI doesn't know"* — it doesn't guess, it identifies exactly who in the building actually does know.

### 3.18 Structured activity capture from any input
- A dedicated **multimodal capture flow** (separate from chat file-attach) takes one audio recording, photo, or document at a time, extracts it, and turns it into an **editable structured draft** (activity type, daily report content, contact, category, challenge) that a rep confirms and binds to a real customer/deal before it's saved as a permanent activity record.
- A rep's daily report doesn't have to be manually typed — a voice memo or a photo of handwritten notes becomes a proper structured CRM record **with a human review step**, not an unverified auto-import.

### 3.19 Pipeline War Room — a time machine for the whole pipeline
- A manager-facing **replay of the last six months of the entire deal pipeline**, recomputed week by week from real deal history by the deterministic engine — press play and watch every deal's health band shift across the weekly snapshots.
- The same rule-based health checks that power live coaching produce every historical frame, so the replay is an **audit trail, not an animation**: any number on screen traces back to the engine's output for that week.
- Turns "how did we get here?" retrospectives into something a manager can literally scrub through in a team meeting.

### 3.20 Command Center — a workspace, not just a chat window
- A persistent, collapsible **context pane** sits alongside the chat at all times — showing a junior rep's own deals/account context, or a manager's whole-team triage view — so the conversation and the underlying data are always visible together.
- Reinforces that Senpai is a working environment for the sales day, not a chatbot bolted onto the side of a separate CRM.

### 3.21 Rep growth tracking
- A dedicated **growth dashboard** turns the coaching history into a longitudinal picture of a rep's development — surfacing concrete skill evidence and improving/declining trends over time, joined to the coaching threads that drove them.
- Makes "is this person actually getting better?" a data question with an auditable answer, not a gut feel.

---

## 4. Under the hood — technical architecture

### 4.1 Self-hosted, fine-tuned model — data sovereignty as a feature
- The reasoning engine is a **fine-tuned, tool-calling model served on hardware you control** (an OpenAI-compatible endpoint on your own GPU) — **customer, deal, and coaching data is never sent to a third-party LLM API.** For a distributor whose brand is trust, this removes the single biggest objection to enterprise AI adoption.
- Because the platform is **deterministic-first**, the entire coaching and health picture — and every dashboard — **still works with the model switched off.** The LLM only rephrases findings the deterministic engine already computed. There is no single point of AI failure.

### 4.2 Relationship Graph Engine ("GraphRAG")
- Captures **global semantic relationships** across the business, versus the purely local view of a normal similarity search or traditional RAG — and does it **faster and cheaper**.
- A real graph data structure (`networkx MultiDiGraph`) built directly over CRM entities — reps, customers, deals, products, industries, categories — with genuine graph-native queries: shortest-path "how are these connected," account-neighborhood expansion, and deal-similarity by shared graph neighbors. This is traversal over real relationships, not a decorative visualization bolted onto unrelated search.
- A **grounding gate**: any AI-written narrative summarizing a market segment is automatically checked against the underlying computed statistics and rejected if the numbers don't match. The model is allowed to *explain* data, never to *invent* it.

### 4.3 Multi-layered tool-loop safety net
Five independent, empirically-tuned guardrails prevent the agent from spiraling, not one simple counter:
1. A hard ceiling of **30 tool-calling rounds** per turn.
2. An **"unproductive rounds" cap** — a tool that returns nothing substantive twice in a row is cut off.
3. **Absolute per-tool call ceilings** within a single turn.
4. **Order-independent duplicate-call detection**, so semantically identical calls with reordered arguments are still caught.
5. **Finish-leak detection** — a specific, subtle failure mode where the model tries to smuggle its final answer inside a tool argument instead of properly finishing; caught and blocked. This level of detail signals the system was genuinely stress-tested against real model failure modes, not just happy-path demoed.

### 4.4 Deterministic-first design philosophy
- **20 independent, rule-based checks** compute the entire coaching and health picture in plain, auditable code before any LLM ever sees the data: 7 deal-health signals, 6 reliability flags, 7 coaching-issue types — each producing a human-readable Japanese explanation.
- This same **"compute first, narrate second"** pattern repeats across the coaching engine, the Ringi Boardroom simulator's objections, the community/segment reports, the account strategy engine, the solution recommendation engine, and the validated-knowledge pipeline — the AI is a translator of verified numbers into natural language, never the source of the numbers themselves.

### 4.5 Cross-chat memory — entity-anchored, token-cheap
- Senpai persists the **judgments** a past conversation reached — not whole transcripts — keyed by subject (account/deal), so a later chat about the same account can reason from what was already concluded.
- These are a handful of compact, **cited** observations instead of replaying entire histories — cheaper on tokens and safer on grounding, and they survive a restart. Built behind a storage seam so it drops onto a real database later without changing callers.

### 4.6 Streaming architecture with dynamic model routing
- Real-time Server-Sent-Events streaming across **15+ endpoints**, carrying **typed events** — prose deltas, resolved tool calls, dynamic model-routing decisions, and reasoning traces — not just raw token text.
- Includes a **dynamic fast-vs-reasoning router**: reasoning is spent only where it changes quality (the final synthesis round), while fast tool-selection rounds stay latency-cheap. Every routing decision carries a human-readable reason — the router is itself explainable.

### 4.7 Security & reliability fundamentals
- Password hashing via **PBKDF2-HMAC-SHA256**.
- Workspace file operations are **sandboxed** with an explicit, tested path-traversal escape guard.
- Dashboard and coaching surfaces have a genuine **offline-fixture fallback** — the UI degrades cleanly instead of going blank when a backend is unavailable.

---

## 5. Why Senpai fits Otsuka Shokai specifically

- **Built on your actual catalog, not a generic CRM demo.** The product taxonomy modeled throughout — 複合機, OA機器, ネットワーク, セキュリティ, PC周辺機器 — is Otsuka Shokai's real business, not a retrofitted generic SaaS category.
- **Your data never leaves your control.** The reasoning model is self-hosted; customer and deal data is never shipped to an external AI vendor. This is the answer to the first question any Otsuka security review will ask.
- **The Ringi Boardroom simulator solves a problem no Western sales-AI vendor even models.** Internal consensus-building is often the actual sales cycle at a company like Otsuka Shokai, and Senpai is the only tool in this evaluation that treats it as a first-class, rehearsable skill.
- **It captures and scales your seniors' judgment.** The validated-knowledge pipeline and Similar Past Cases turn interviews with your best reps into a reusable, auditable asset — directly addressing knowledge loss on attrition and retirement.
- **Fully bilingual from day one** — deployable to a Japanese-first workforce today without a separate localization project, and equally usable by any international team members.
- **Designed to scale senior mentorship, not replace it** — the coaching loop makes every senior rep's judgment reusable across an entire junior cohort, addressing a workforce structure with a large junior-rep base and a limited number of senior mentors.
- **Radically auditable, by construction** — every tool call, every generated number, every AI narrative, every coaching recommendation, and every piece of shown knowledge is traceable back to real data or explicitly gated against it. This matches an enterprise, and specifically a distributor whose entire brand promise is reliability, precisely where a typical "black box AI" pitch would fail an internal trust review.
- **A real, working, end-to-end system today** — not a slide deck of future features. 38 working tools, a large automated test suite, a functioning admin cost-tracking dashboard, and a live training simulator all exist and run, in one live demo, right now.
- **The first 30 seconds sell it** — a first-visit cinematic intro (2,200 particles drawing 大塚商会 → a living knowledge graph → 先輩, with fully bilingual narration) makes the landing page itself a statement of the product's polish before a single click.

---

## 6. By the numbers

| Metric | Value |
|---|---|
| Distinct tools available to the agent | **38** |
| Max tool-calling rounds per single conversation turn | **30** |
| Deterministic coaching/health rules (no LLM guessing) | **20** (7 health signals + 6 reliability flags + 7 coaching issues) |
| Coaching Explainability dimensions per recommendation | **4** (trigger · evidence · similar cases · outcome stats) |
| Independent tool-loop safety guardrails | **5** |
| Output formats generated from one document render | **3** (PPTX + PDF + HTML) — plus native DOCX |
| Admin portal views | **11** |
| Streaming endpoints (typed SSE events) | **15+** |
| Deal pipeline stages modeled | **8** (Confirmed → A+ → A → B → C → P → Lost → Cancelled) |
| Pipeline War Room replay horizon | **6 months**, recomputed weekly by the deterministic engine |
| Prototype dataset scale | **24 reps · 150 customers · 520 deals** |
| Validated senior-sales principles (interview-traceable) | **P001–P011+**, human-reviewed before shown |
| Web crawl depth | up to **5 sites × 3 pages** (research) · up to **12 pages** (single-site `/intel`) |
| Multi-agent personas per `/crew` analysis | **3** (Researcher, Coach, Strategist) |
| Ringi Boardroom persona levels | **3** (課長 → 部長 → 社長) |
| Regions modeled for tailored advice | **2** (関東 Kanto / 関西 Kansai) |
| Reasoning model | **fine-tuned, self-hosted** (OpenAI-compatible endpoint on your own GPU) |

---

## 7. Selling-point vocabulary (use throughout)

Weave these terms consistently — they are the language an Otsuka Shokai decision-maker wants to hear:

**Multimodal · Highly agentic · Deterministic-first (決定論ファースト) · No hallucination / zero-hallucination guardrails (ハルシネーション無し) · Self-hosted / data sovereignty (自社データ主権) · Human-in-the-loop (人手承認) · Provenance-tracked (来歴追跡) · Citation-firewalled (引用ファイアウォール) · Grounding gate (根拠ゲート) · Audit trail (監査証跡) · Evidence-grounded · Case-based reasoning (事例ベース) · Explainable / radically auditable (説明可能) · Region- and deal-size-aware · Fully bilingual (完全バイリンガル) · Scales the senpai-kohai relationship (先輩-後輩) · A real, working, end-to-end system today.**
