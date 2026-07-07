# Senpai — Content Reservoir for Supplementary One-Pager

Everything verified against the actual codebase (file:line references kept where useful). Written in the confident, quantified register you'd use in front of Otsuka Shokai management — trim/select from this when you lay out the final landscape A4 page. A "presenter notes" section at the bottom flags anything to NOT claim out loud.

---

## 1. Positioning

**Senpai** — an AI sales co-pilot that gives every junior rep a senior mentor on demand, and every manager a real-time, evidence-based coaching lens — grounded entirely in Otsuka Shokai's own deal data, product catalog, and sales process.

One-line pitch: *"Senpai doesn't replace the senpai-kohai relationship that makes Japanese sales teams work — it scales it."*

---

## 2. The problem this solves

- A junior rep needs a senior's judgment at 11pm before a big call tomorrow. A human senpai's time doesn't scale past a handful of kohai.
- The real bottleneck in enterprise sales in Japan is frequently not the customer meeting — it's internal consensus-building (稟議, ringi). This is a distinctly Japanese sales-process problem that generic, Western-built sales AI tools don't model at all.
- A sales manager responsible for a full team cannot manually read every daily report from every rep and still catch the one that's quietly going off the rails.
- Decades of product knowledge and winning-deal patterns live in senior reps' heads — hard to transfer, harder to scale, easy to lose on attrition/retirement.
- Enterprise AI tools are frequently black boxes; a company whose brand is built on trust and reliability cannot adopt an AI system that can't show its work.

---

## 3. Core product capabilities (rep + manager facing)

### 3.1 Agentic tool-calling engine
- **38 distinct tools** spanning CRM/deal lookup, product catalog, quoting, communications, calendar, document generation, web research, and workspace file management.
- A single conversation turn can chain **up to 30 rounds** of tool calls — the system is architected for genuinely long, multi-step reasoning chains, not single-shot Q&A.
- Every tool call is rendered in the UI as an inspectable card: exact query, exact arguments, exact result — a rep or manager can verify precisely what Senpai looked up, not just trust a generated summary.
- No slash command is required for this — natural language alone ("アクメ商事の案件どうなってる？") triggers the right tool automatically, in Japanese or English.

### 3.2 Local file & knowledge retrieval (RAG)
- Ingests PDF, DOCX, PPTX, XLSX, TXT, and Markdown directly from chat — text extraction feeds straight into the grounded tool-calling loop, not a black-box summarizer.
- A dedicated sandboxed workspace file system lets Senpai search, read, edit, and move documents a rep uploaded days ago, without re-attaching them.
- Backed by a **hybrid retrieval engine**: BM25 keyword search (Japanese-aware, POS-filtered tokenization) fused with multilingual dense embeddings via **reciprocal rank fusion** — with a 3-tier graceful degradation path (dense+BM25 → BM25-only → keyword substring) so retrieval never goes fully dark, even if an embedding service is unavailable. Vector index is pre-built offline, so query-time retrieval needs no GPU.

### 3.3 Live web research
- Two distinct web tools: a fast **web search** (Tavily-backed) for quick facts, and a genuine **multi-page crawl** using a real headless browser (Playwright) — visiting up to 6 pages across up to 3 sites per request, then synthesizing a cited answer.
- The `/intel` flow streams the crawl **live** — real screenshot frames, current URL, and running counts of products/news/PDFs discovered, rendered in the browser as it happens. This is not a cached search result; it's an actual browser session a judge can watch execute in real time.

### 3.4 Document generation pipeline
- Natural-language triggers generate a **提案書 (proposal)**, **稟議書 (ringisho)**, or a general slide deck — no confirmation dialog, the system generates immediately once grounded on real data.
- One HTML deck is rendered first; a headless Chromium instance exports a pixel-perfect PDF, then measures every text box in that same HTML to bake matching, genuinely **editable text boxes into a real PPTX** over a decorative screenshot background — not a flattened image pretending to be a slide.
- **3 output formats (PPTX + PDF + HTML) generated from a single source render**, with a pure-Python fallback path if a browser engine is unavailable.
- Document generation itself is internally grounded — it re-calls the CRM lookup and web search tools as part of its own execution, so even a "just make me a deck" request is fact-checked against real data before it renders.

### 3.5 Multi-agent deal & team analysis
- `/crew <deal>` — three agents (Researcher, Coach, Strategist) analyze one deal in sequence, with a visible execution timeline showing each phase before the final brief renders.
- `/team` (manager-only) — the same three-agent analysis fanned out across an entire team, plus a consolidated team-lead action list, in one request.

### 3.6 Ringi Boardroom — a training simulator built for a uniquely Japanese sales problem
- A rep picks a real, at-risk deal and rehearses the internal 稟議 approval process against three escalating personas — 課長 (section chief), 部長 (department head), 社長 (president) — each raising objections generated from the deal's actual, real flagged issues, not scripted dialogue.
- A live approval gauge ticks in real time as the rehearsal proceeds; a "Senpai HUD" surfaces coaching whispers tied directly back to the underlying data.
- After a failed run, the rep applies a suggested intervention and **re-runs the exact same simulation** — because objections are generated from real computed deal state, fixing the underlying issue visibly changes the outcome, closing the loop between coaching advice and consequence.
- This is, to our knowledge, a category of sales-training tool that does not exist in mainstream Western sales-enablement software — it is built specifically around the way enterprise sales actually gets approved inside a Japanese company.

### 3.7 Manager coaching loop
- A deterministic (not LLM-guessed) issue-detection engine flags **7 distinct coaching issue types** per rep — confidence/reality mismatch, missing decision-maker, inactivity, premature discounting, repeated unresolved issues, weak discovery, incomplete reporting.
- A "Needs Coaching" queue surfaces flagged reps automatically; a "Confidence vs. Reality" view compares a rep's self-assessment against what the data actually shows.
- Every flagged issue can be escalated into a coaching thread (a persistent chat between manager and rep); a longitudinal progress tracker measures whether a rep's flagged issue rate actually declined after a coaching conversation — a genuine "did coaching work" signal over time, not a one-off note.

### 3.8 Admin / operations portal
- **11 distinct admin views**: Overview, People, Org & Assignments, Activity, LLM Usage, Pipeline Health, System Status, and a 4-view Visualization suite (Network graph, Communities, Live retrieval, GraphRAG-vs-traditional comparison).
- Org reassignment (moving a rep to a different manager) takes effect live, with an immediate API-backed update — not a mocked control.
- A real, per-call **token/cost usage ledger** — every LLM invocation logged with real-vs-estimated token counts, rolled up per day, per model, per prompt label, feeding a live spend dashboard with a configurable cost-per-1K-token rate.

### 3.9 Fully bilingual, day one
- **998 translation keys** across the entire product — not just labels, but coaching content, tool-call names, slash-command descriptions, and the training simulator UI — switch instantly between Japanese and English with one click, no page reload.

### 3.10 Account intelligence & strategic planning
- A dedicated **account plan view** (separate pages for rep and manager) showing account health, growth trajectory, and concrete expansion opportunities for any customer — not buried in chat, a standalone strategic workspace.
- Powered by a real deterministic engine (health/trajectory/expansion/strategy scoring modules) plus an on-demand, grounded AI commentary layer — the same "compute first, narrate second" philosophy as the coaching engine, applied to account strategy.
- The same expansion-opportunity signals feed directly into the recommendation engine below — one computed account picture, reused everywhere it's relevant, not recomputed ad hoc per feature.

### 3.11 Solution recommendation engine — a second, independent grounding firewall
- Goes meaningfully beyond a keyword/category filter: candidate solutions are generated from **two signal layers** (category/industry match plus real account-expansion signals) and scored with a confidence-weighted ranking (multipliers of 1.6× / 1.3× / 1.1× by confidence tier) before any AI text is generated.
- The explanation step is **citation-firewalled**: the model may only narrate the closed, pre-ranked candidate list, and any citation it produces is checked against the allowed set and stripped if it doesn't verify. This is a second, independently-implemented instance of the same anti-hallucination pattern used in the GraphRAG grounding gate — evidence this is a deliberate, repeated architectural principle across the codebase, not a one-off trick.

### 3.12 Instant, catalog-grounded quoting
- Generates a real structured price quote — line items resolved against actual product-catalog pricing, with computed subtotal, discount, tax, and grand total — not a fabricated number.
- Explicitly and unambiguously labeled as a draft that is never auto-sent or persisted without a human in the loop.

### 3.13 Communication & scheduling actions
- `draft_message` and email drafting are **draft-only by hard code path, not just by prompt instruction** — there is no send function wired up at all, so a customer-facing message physically cannot be sent without a human copying it out.
- Meeting scheduling goes a step further: it integrates with the **real Google Calendar API** to actually book a calendar hold, with a simulated-confirmation fallback only if calendar credentials are unavailable. This is a genuine, deliberate design distinction — advisory, customer-facing actions stay human-gated, while a low-risk internal action (holding time on a calendar) can be executed directly by the agent.

### 3.14 "Know when to hand off" — the route-to-expert safety valve
- When a question is outside what Senpai should answer alone, `route_to_expert` doesn't just say "ask someone senior" — it scores every senior/expert rep in the org against the actual question, using real specialty-tag overlap, keyword matching, and a top-performer boost, and names the single best-matched real internal expert plus a draft outreach message.
- This is a concrete answer to the natural enterprise objection "what happens when the AI doesn't know" — it doesn't guess, it identifies exactly who in the building actually does know.

### 3.15 Structured activity capture from any input
- A dedicated capture flow (separate from chat file-attach) takes one audio recording, photo, or document at a time, extracts it, and turns it into an **editable structured draft** (activity type, daily report content, contact, category, challenge) that a rep confirms and binds to a real customer/deal before it's saved as a permanent activity record.
- Means a rep's daily report doesn't have to be manually typed — a voice memo or a photo of handwritten notes becomes a proper structured CRM record with a review step, not an unverified auto-import.

### 3.16 Command Center — a workspace, not just a chat window
- A persistent, collapsible context pane sits alongside the chat at all times — showing a junior rep's own deals/account context, or a manager's whole-team triage view — so the conversation and the underlying data are always visible together.
- Reinforces that Senpai is a working environment for the sales day, not a chatbot bolted onto the side of a separate CRM.

---

## 4. Under the hood — technical architecture

### 4.1 Relationship Graph Engine ("GraphRAG")
- A real graph data structure (`networkx MultiDiGraph`) built directly over CRM entities — reps, customers, deals, products, industries, categories — with genuine graph-native queries: shortest-path "how are these connected," account-neighborhood expansion, and deal-similarity by shared graph neighbors. This is traversal over real relationships, not a decorative visualization bolted onto unrelated search.
- A **grounding gate**: any AI-written narrative summarizing a market segment is automatically checked against the underlying computed statistics and rejected if the numbers don't match. The model is allowed to *explain* data, never to *invent* it.
- An honest, **measured 3-way benchmark** exposed directly in the admin portal — the same query run through the graph-based approach, a naive one-hop graph baseline, and traditional hybrid search, reporting real latency, context size, and token counts side by side for each. This is a rigorous, self-critical evaluation harness few teams build for their own retrieval system — it doesn't just claim graph retrieval is better, it measures and displays exactly where and by how much.

### 4.2 Dependency-aware parallel execution engine
- Every batch of tool calls the model requests in a single round is scheduled as a genuine dependency graph: read-only tool calls execute in parallel, while any write/external-effect call becomes a serialization barrier that later calls must wait on — correctness-preserving concurrency, not a naive sequential loop.
- Includes real engineering most hackathon projects skip entirely: **cycle detection** (DFS-based) before execution, per-task **retries and timeouts**, **cooperative cancellation** (a failing task can stop not-yet-started sibling tasks mid-run), and **mid-run fan-out** (the plan can grow while it's executing, not just at the start).
- The same engine powers document generation via a fixed two-level gather → synthesize plan — multiple context-gathering steps run in parallel, feeding one terminal synthesis step.

### 4.3 Multi-layered tool-loop safety net
Five independent, empirically-tuned guardrails prevent the agent from spiraling, not one simple counter:
1. A hard ceiling of 30 tool-calling rounds per turn.
2. An "unproductive rounds" cap — a tool that returns nothing substantive twice in a row is cut off.
3. Absolute per-tool call ceilings within a single turn.
4. Order-independent duplicate-call detection, so semantically identical calls with reordered arguments are still caught.
5. **Finish-leak detection** — a specific, subtle failure mode where the model tries to smuggle its final answer inside a tool argument instead of properly finishing; caught and blocked. This level of detail signals the system was genuinely stress-tested against real model failure modes, not just happy-path demoed.

### 4.4 Deterministic-first design philosophy
- **20 independent, rule-based checks** compute the entire coaching and health picture in plain, auditable code before any LLM ever sees the data: 7 deal-health signals, 6 reliability flags, 7 coaching-issue types — each producing a human-readable Japanese explanation.
- This same "compute first, narrate second" pattern repeats across the coaching engine, the Ringi Boardroom simulator's objections, the community/segment reports, the account strategy engine, and the solution recommendation engine — the AI is a translator of verified numbers into natural language, never the source of the numbers themselves.
- Critically, this isn't one clever trick applied once — it's the same architectural principle **independently implemented at least twice** with real enforcement: the GraphRAG community narratives are number-checked and rejected on mismatch, and separately, the solution recommendation engine's citations are checked against an allowed list and stripped if invalid. Two independent code paths enforcing the same discipline is a much stronger claim than one. This is the core trust argument for a conservative enterprise buyer: **the AI cannot hallucinate a deal's health score or a recommendation's grounding, because in both cases it never computes the underlying number or citation itself.**

### 4.5 Streaming architecture
- Real-time Server-Sent-Events streaming across 15+ endpoints, carrying **typed events** — prose deltas, resolved tool calls, dynamic model-routing decisions, and reasoning traces — not just raw token text.
- Includes dynamic **fast-vs-reasoning model routing per turn**, chosen automatically based on the complexity of the request.

### 4.6 Frontend engineering
- A custom, purpose-built streaming state store (`useSyncExternalStore`-based) solves a genuine Next.js bug: normally, navigating to a different page mid-response kills the in-flight AI response. Senpai keys state outside the component tree so a streaming answer survives route navigation — a specific, real bug most teams never even notice, let alone fix correctly.
- Voice dictation (browser `MediaRecorder`, with codec-support probing) and file/image upload are unified through the same server-side extraction pipeline — one code path handles a typed message, an uploaded document, a photo, or a recorded voice memo.
- Correct low-level SSE parsing that handles frame boundaries split across network chunk arrivals — a detail easy to get subtly wrong and rarely tested.

### 4.7 Security & reliability fundamentals
- Password hashing via PBKDF2-HMAC-SHA256 with **120,000 rounds** and a per-user salt, verified with constant-time comparison — standard cryptographic hygiene done correctly.
- Workspace file operations are sandboxed with an explicit, tested path-traversal escape guard.
- Dashboard and coaching surfaces have a genuine offline-fixture fallback — if the backend is unreachable, the app degrades gracefully to real, interview-derived sample data rather than a blank screen.

### 4.8 Testing discipline
- **535 automated tests**, including a dedicated regression test for the tool-loop safety guardrails and a dedicated test verifying the workspace sandbox blocks path-traversal escapes — evidence of testing against real, specific failure modes rather than only happy-path coverage.

---

## 5. Why Senpai fits Otsuka Shokai specifically

- **Built on your actual catalog, not a generic CRM demo.** The product taxonomy modeled throughout — 複合機, OA機器, ネットワーク, セキュリティ, PC周辺機器 — is Otsuka Shokai's real business, not a retrofitted generic SaaS category.
- **The Ringi Boardroom simulator solves a problem no Western sales-AI vendor even models**: internal consensus-building is often the actual sales cycle at a company like Otsuka Shokai, and Senpai is the only tool in this evaluation that treats it as a first-class, rehearsable skill.
- **Fully bilingual from day one** — deployable to a Japanese-first workforce today without a separate localization project, and equally usable by any international team members.
- **Designed to scale senior mentorship, not replace it** — the coaching loop makes every senior rep's judgment reusable across an entire junior cohort, addressing a workforce structure with a large junior-rep base and a limited number of senior mentors.
- **Radically auditable, by construction** — every tool call, every generated number, every AI narrative is traceable back to real data or explicitly gated against it. This matches an enterprise, and specifically a distributor whose entire brand promise is reliability, precisely where a typical "black box AI" pitch would fail an internal trust review.
- **A real, working, end-to-end system today** — not a slide deck of future features. 38 working tools, 535 passing tests, a functioning admin cost-tracking dashboard, and a live training simulator all exist and run, in one live demo, right now.

---

## 6. By the numbers

| Metric | Value |
|---|---|
| Distinct tools available to the agent | **38** |
| Max tool-calling rounds per single conversation turn | **30** |
| Deterministic coaching/health rules (no LLM guessing) | **20** (7 health signals + 6 reliability flags + 7 coaching issues) |
| Independent tool-loop safety guardrails | **5** |
| Output formats generated from one document render | **3** (PPTX + PDF + HTML) |
| Admin portal views | **11** |
| Bilingual UI translation keys | **998** |
| Automated tests | **535** |
| Password hashing rounds | **120,000** (PBKDF2-HMAC-SHA256) |
| Deal pipeline stages modeled | **8** (Confirmed → A+ → A → B → C → P → Lost → Cancelled) |
| Prototype dataset scale | **24 reps · 150 customers · 520 deals** |
| Web crawl depth per `/intel` request | up to **6 pages across 3 sites** |
| Multi-agent personas per `/crew` analysis | **3** (Researcher, Coach, Strategist) |
| Ringi Boardroom persona levels | **3** (課長 → 部長 → 社長) |
| Independent anti-hallucination "grounding gate" implementations | **2** (GraphRAG community narratives + solution recommendation citations) |

### A single demonstrated conversation turn:
One numbered, multi-part request in plain Japanese can be shown to deterministically fire **13 grounded tool calls in a single parallel batch**, before the model even begins reasoning — with several more added organically to close out the request (web check, health scoring, recommended actions), typically totaling **16–20 tool calls resolved in one turn**. (See `SENPAI_DEMO_SCRIPT.md`, "THE MEGA-PROMPT" section, for the exact reproducible prompt and line-by-line trace against the source.)

---

## 7. Presenter notes — do not overclaim these live

**⚠️ Live-demo safety warning, check this before you present:** `schedule_meeting` defaults to actually executing, not just drafting — if real Google Calendar credentials are configured in the demo environment, running any prompt that invokes it (including the "mega-prompt" comparison variant in `SENPAI_DEMO_SCRIPT.md` that asks it to "tentatively hold a meeting") will create a **real calendar event**, not a mock. Before presenting: either confirm the demo environment has no live Google Calendar credentials wired up, or avoid prompts that trigger scheduling, or explicitly instruct Senpai not to confirm the booking in the prompt itself. Don't find this out live in front of Otsuka Shokai management.

Also keep these in mind for Q&A; none of them belong on the client-facing page, but a technical judge may probe:

- **Signup only supports junior reps today** — a new junior signup creates a brand-new rep record (not "adopting" an existing seeded one) and is assigned to an existing manager. **There is no manager self-signup** — manager accounts must be pre-provisioned. If asked "can a new manager onboard themselves," the honest answer is not yet.

- **Auth tokens are issued but not yet enforced** on protected endpoints — real password hashing exists, but session enforcement is not yet wired up everywhere. Don't claim "production-hardened security."
- **No rate limiting and no explicit prompt-injection defenses** exist yet.
- **"GraphRAG" community/segment detection is a fixed Category × Industry partition**, not a machine-learned clustering algorithm (no Louvain/Leiden) — be precise if asked "what clustering algorithm," the honest answer is "deterministic segmentation, not ML clustering."
- **The "DAG" tool executor is a within-round parallelizer**, not a multi-step autonomous planner — dependencies are structurally fixed (reads parallel, writes serialize), not dynamically planned by the model across rounds.
- **In-chat web-research crawl replay is post-hoc playback** of already-captured frames, not literally live — only the standalone `/intel` page streams genuinely live screenshots frame-by-frame. Use `/intel` specifically if you want to show a truly live crawl.
- **Multimodal audio/image ingestion makes real API calls** (Whisper transcription, vision-model image extraction) but gracefully degrades to fixed mock text if no API key/model is configured — accurate to call it "real, API-key-gated," not "always live."
- **No dedicated hallucination/grounding CI eval suite** exists beyond the graph grounding gate and ad hoc dev scripts — don't claim a formal eval framework beyond what's described above.
