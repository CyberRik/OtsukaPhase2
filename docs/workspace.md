# Senpai Workspace

The **Workspace** is Senpai's unified conversational surface. It replaces two
separate pages — the standalone **Assistant** (a tool-calling chat) and the
**Review Coach** (a deal-review form) — with one thread where deterministic
*skills*, grounded *artifacts*, and ordinary conversation live side by side.

> **Thesis.** Skills are deterministic artifact producers, invoked by explicit
> slash commands. Artifacts are immutable, ID-grounded records. Conversation is
> the glue that threads them together. *Trust beats cleverness* — Senpai would
> rather miss than fabricate the wrong customer's facts.

This doc covers the Workspace front end and the contract it expects from the
bridge. The streaming/LLM side is documented in [`llm_bridge.md`](llm_bridge.md).

---

## Why it exists

The two old surfaces overlapped badly:

| Old surface | What it did | Limitation |
|---|---|---|
| **Review Coach** (`/coach`) | One deal note → 6 deterministic teaching sections + a streamed "senior's read". | A form, not a conversation. No follow-up. No web/account context. |
| **Assistant** (`/assistant`) | Free-form chat → LLM tool-loop (`score_deal_health`, `find_deals`, …). | No deterministic artifacts; grounding lived only in transient tool calls. |

The Workspace keeps both strengths in one thread: explicit skills produce the
**deterministic, pinned artifacts** the Coach was good at, while bare turns run
the **same tool-calling chat** the Assistant was good at — with one shared
conversation memory across all of them.

---

## The three skills

A skill is invoked by an **explicit slash command** (`web/components/workspace/slash.ts`).
The *user*, never an intent-classifier, decides which deterministic engine runs —
that keeps the trust boundary legible. Unknown commands are rejected, not
silently reinterpreted.

| Command | Backend | Produces | Grounded on |
|---|---|---|---|
| `/review <note or deal id>` | `POST /api/coach/review` + `coach/narrate` (SSE) | **review** artifact — 6 teaching sections + streamed senior's read | a deal (`D…`), principles (`P…`/`I…`), playbooks (`PB…`) |
| `/account <name or id>` | `GET /api/account/{id}` + `account/commentary` (SSE) | **account_brief** artifact — overview, risk signals, expansion, focus + streamed account read | a customer (SPR records: quotes, orders) |
| `/research <question>` | `POST /api/chat` (role=research) → `research_stream` (SSE) | **research** artifact — source ledger + grounded answer + web citations | internal records first, web only as labelled fallback |
| *(bare turn, no slash)* | `POST /api/chat` (junior/manager tool-loop) | a normal chat reply (tool ledger when tools fire) | whatever tools the loop calls |

---

## The Artifact model (`web/lib/artifacts.ts`)

An **Artifact** is the typed, **immutable**, grounded output of a skill — a
first-class thread entry, not free prose. Two invariants protect the trust
proposition:

1. **Immutability.** A skill never edits an artifact in place. Re-running a skill
   *appends* a new artifact that `supersedes` the previous one, so every artifact
   is a faithful record of what was true, with what evidence, at one moment.
2. **Deterministic provenance.** `evidence` carries **source IDs only** (deal /
   SPR / principle / playbook / web) — **never human names**. The assemblers
   derive evidence from the deterministic engine output; the LLM is never the
   source of an evidence entry.

```ts
interface Artifact {
  id; kind: "review" | "account_brief" | "research";
  threadId; turnId;                 // thread + turn it belongs to
  entity?: { type: "deal" | "account"; id; name };  // what it's ABOUT
  band?: "red" | "yellow" | "green";
  sections: ArtifactSection[];      // the DETERMINISTIC record
  evidence: EvidenceRef[];          // IDs only, never names
  commentary?: string | null;       // the streamed senior read (presentation)
  producedBy: "review@1" | "account_brief@1" | "research@1";
  supersedes?: string;              // immutability chain
  status: "building" | "ready" | "unavailable";
}
```

The three pure assemblers — `assembleReviewArtifact`, `assembleAccountArtifact`,
`assembleResearchArtifact` — map the **existing** API payloads into artifacts and
**add no facts**. Evidence IDs are parsed only from structured `出典` (source)
segments with a strict ID shape (`/^(PB\d+|P\d+|I\d+|D\d+)$/`), so a stray human
name can never become evidence.

### Unified rendering (`web/components/workspace/cards/artifact-body.tsx`)

The three skills used to have three duplicated card renderers
(`review-card.tsx`, `account-card.tsx`, `research-card.tsx`). They were collapsed
into a single **`ArtifactBody`** driven by a `KIND_META` table (per-kind header,
alert, and commentary placement). `artifact-card.tsx` is now a one-line
dispatcher. Shared sub-components: `Markdown`, `SectionBlock`, `CommentaryBlock`,
`EvidenceDrawer`.

---

## Export to Excel (`web/lib/artifact-export.ts`)

Every **ready** artifact carries an **Export** button (header, beside the band
chip in `ArtifactBody`) that downloads a real multi-sheet `.xlsx`.

The key design property: export is a **serializer, not a generator**. It only
reformats an already-grounded, immutable artifact — it adds no facts and the LLM
touches nothing on this path. The same trust model as the rest of the Workspace:

- **Two sheets.** *Brief* (heading + meta + each section + the senior's-read
  commentary) and *Sources* (the evidence table: deal / SPR / principle /
  playbook / web IDs + URLs). Provenance travels **into** the file, so the
  workbook stays auditable after it leaves Senpai.
- **Grounded cells only.** Values come straight off `artifact.sections` /
  `commentary` / `evidence`; a footnote states that cells with no source are
  left blank — fabrication can't enter via export.
- **Fully client-side.** `write-excel-file/browser` is dynamically imported
  inside `downloadArtifact` (kept out of the SSR bundle) and the download runs
  via `.toFile()`. No bridge round-trip — the artifact is already a typed object
  in the page.
- **Generic over the artifact shape.** Free for `/review`, `/account`,
  `/research` today and for any future skill (the `/prep`, `/recover`, `/expand`
  workflow agents) the moment it emits an artifact.

The `contentSheet` / `sourcesSheet` builders are the only Excel-aware seam. The
serializer first shipped as CSV; it was upgraded to a true multi-sheet `.xlsx`
(dependency: `write-excel-file`, which pulls `fflate` for the zip).

---

## Shared conversation memory

The headline fix of this session. Previously each card keyed its own
`conversation_id` off the message text, so there was **no real history** — a
follow-up question started cold.

Now **one `threadId`** (`artifact.threadId`) is the conversation id across *every*
skill turn and chat turn in the thread:

- The front end builds a real transcript (`buildChatHistory`) — user text,
  assistant answers, and skill turns labelled with their entity + cached
  commentary — and passes it as history on each chat call.
- The bridge **cross-seeds focus** (`_seed_chat_focus` in `server.py`): when a
  skill turn grounds on a customer/deal, that focus is written into the
  conversation's `_CHAT_CONTEXTS`, so a later bare turn ("what's their pipeline?")
  inherits the entity instead of re-resolving from scratch.

**Verified live:** `/review D001` followed by a bare follow-up resolves to the
seeded customer; a *fresh* conversation does not — focus is correctly scoped to
the thread.

---

## Grounding & the in-place pick flow

The Workspace inherits the bridge's **resolution trust model** (see
[`llm_bridge.md`](llm_bridge.md)): only *high-confidence* matches (exact id /
alias / deal id) auto-ground. *Medium* (fuzzy) and *low* (name-extracted)
matches surface **candidates** and never ground.

Two pick-flow bugs were fixed:

1. **The senior's read used to spawn before the user chose** among ambiguous
   companies. The bridge now **short-circuits**: if there's no customer context
   but there *are* ambiguous candidates, it emits `awaiting_choice` then `done`
   and runs **no LLM read**.
2. **Picking a candidate used to continue in a different chat.** Resolution now
   happens **in place**: `onPick(turnId, deal, name)` re-runs the grounded
   skill and **replaces the same message's artifact** (the turn is keyed
   `key={m.artifact.id}` so it remounts and streams the grounded read into the
   same card). When candidates are present, the turn renders **only** the
   picker — no card, no read — until a choice is made. This in-place flow now
   covers **all three skills** (`/review`, `/account`, `/research`) **and plain
   chat**; `/account` and `/research` were brought to parity with `/review` (the
   latter also gained a picker it previously lacked entirely). The chat pick
   re-runs the same assistant turn grounded on the choice by bumping a `runId`
   (`ChatTurn` is keyed on it, so it remounts with a fresh cache slot and streams
   the grounded answer into the same turn — no new user bubble).

Follow-on fixes:

3. **Card showed sources but no read.** The research pipeline emits its
   synthesis as a single `answer` event (not a `delta` stream like chat).
   `ResearchTurn` only handled `delta`, so the senior's read was silently
   dropped — sources + evidence rendered, commentary was empty. It now handles
   `answer` (and surfaces `unavailable`/`error` with a short note, so a dead LLM
   bridge is never a silent empty card).
4. **Ambiguity produced redundant "which one?" text next to the picker.** This
   happened on **both** ambiguity paths and was fixed in both:
   - `research_stream` emitted the `resolve` candidates *and* an
     `_ambiguity_answer` markdown table.
   - the **chat tool-loop** emitted the candidates *and* let the LLM generate a
     "Clarification Needed — which customer?" message (driven by a now-removed
     `【顧客の曖昧性】` system clause).

   Both now emit **only** the candidates and `done` (the chat path `return`s
   before the LLM runs). The deterministic picker is the whole response. The chat
   turn treats "has candidates" as a valid terminal state so the now-empty answer
   isn't flagged as an error. *(The `/research` deal-choices answer is kept — that
   path has no picker.)*

---

## The Experience panel (`web/components/coach/similar-cases.tsx`)

A shared "経験 — 過去の案件と原則 / Experience — past cases & principles" surface
brings the Review Coach's grounding to the Workspace. `ExperiencePanel` is a
collapsible block under a review artifact that:

- shows **relevant principles** (`relevantPrinciples()` ranks human-approved
  principles by keyword overlap with the deal), and
- **lazily fetches similar past win/loss cases** when opened.

It reuses `PRINCIPLE_KEYWORDS` / `customerText` / `principleText` from
`content-i18n` and is shared so the standalone Coach and the Workspace render
identical Experience UI.

---

## Composer controls: Stop & Clear

- **Stop** — chat turns carry an `AbortController` (`ctrlRef`) + `abortedRef`.
  While a turn is running a **Stop** button (square icon) appears; an intentional
  stop keeps the partial output as `done`, not `error`.
- **Clear** — `clearThread()` empties the transcript, resets the input and the
  attached deal, and calls `thread.reset()` on the external store.
- **Deal pill** — a `Building2`/`Paperclip` chip attaches a specific deal to the
  next turn (accent-styled when set), so `/review` and follow-ups can target a
  deal without retyping its id.

---

## Normal chat still works

A specific user concern: *"normal chats won't work anymore? … I want normal
chats to work as well like they were doing for assistant and review coach."*

They do. A bare (no-slash) turn hits the **same `POST /api/chat`** endpoint the
Assistant used. That endpoint answers **plainly when no tool is needed** and only
calls a tool when the question warrants one — the Workspace renders the shared
`MessageBubble` (`web/components/assistant/message.tsx`) exactly like the
Assistant did, including the tool ledger, grounding/routing badges, and the
"General answer (no tools)" badge. A "couldn't reach the server" error means the
**LLM endpoint (:8765) is down**, not that chat is broken.

`MessageBubble` and its types (`Msg`, `ToolCall`, `SourceState`, `WebCitation`)
were extracted out of `assistant-chat.tsx` into `message.tsx` so both surfaces
share one renderer (the Assistant file shrank by ~250 lines).

---

## State that survives navigation

The transcript and each card's streamed commentary live in a **keyed external
store** (`web/lib/chat-store.ts`) read via React `useSyncExternalStore`, so an
in-flight generation survives navigating away and back — same mechanism the
standalone Coach and Assistant used. `StrictMode` double-mounts are guarded by a
`startedRef` + a cached `started` flag so a stream is never kicked off twice.

---

## Manager parity

`Workspace({ examples, deals, principles, role })` takes a `role`. The manager
route (`web/app/manager/workspace/page.tsx`) renders the same shell with
`role="manager"`, so bare turns run the **manager tool-loop** (team pipeline /
at-risk deals / coaching focus). Both routes load `api.coachExamples()`,
`api.dashboard()`, `api.principles()`. The manager nav got a Workspace entry
(`app-shell.tsx`). This manager surface is what lets the standalone manager
Assistant be retired too.

---

## Consolidation status (toward deleting the old pages)

| Phase | State |
|---|---|
| 1 — Artifact model + `/review` | ✅ done |
| 2 — `/account`, `/research`, bare chat | ✅ done |
| 3 — shared memory, unified cards, Experience panel, stop/clear, manager workspace | ✅ done |
| 3.5 — full parity audit + close residual gaps (senior-tip chips, principle provenance/verbatims) | ✅ done |
| 4 — flip nav to Workspace-first | ✅ done |
| 5 — delete `assistant/` + `coach/` pages (engines stay) | ✅ done |

The standalone pages have been removed. Deleted: `app/junior/assistant/`,
`app/manager/assistant/`, `app/junior/coach/`, `components/assistant/assistant-chat.tsx`,
`components/coach/coach-chat.tsx`, and the `nav.assistant` / `nav.coach` sidebar
entries. **Kept** (the Workspace depends on them): `assistant/message.tsx`,
`assistant/retrieval-explorer.tsx`, `coach/similar-cases.tsx`, and
`coach/explainability-card.tsx` (still used by the manager coaching page). The
deterministic **engines** (`coach/`, `assistant` tool-loop) are *not* going away
— only the duplicate pages. The junior home quick-action now points at
`/junior/workspace`; `manager/coaching` (coaching analytics) is unaffected.

### Parity audit (what each old page had vs the Workspace)

**Assistant** — full functional parity. Both surfaces share the same
`MessageBubble` renderer and the *identical* `chatStream` event handling (tool
ledger, grounding/routing badges, RetrievalExplorer, research source ledger, web
citations, ambiguous-customer picker, stop, clear, per-thread `conversationId`).
Nothing functional is exclusive to the Assistant page. *Minor, non-blocking:* the
Assistant surfaces curated example chat prompts (incl. manager ones like "team
pipeline overview") that the Workspace landing doesn't pre-list — the user can
still type them.

**Review Coach** — parity reached after closing two gaps:

| Coach feature | Workspace |
|---|---|
| 6 deterministic lens sections | ✅ artifact sections (`ArtifactBody`) |
| Reality-check red intercept | ✅ `alertKey: "reality_check"` |
| Top priority actions | ✅ `priority_actions` section |
| Streamed senior's read + grounding/model badge | ✅ `ReviewTurn` + `CommentaryBlock` |
| Ambiguous-customer picker | ✅ in-place pick (re-grounds the same turn — better than the old global-event flow) |
| Similar past cases | ✅ `ExperiencePanel` → `SimilarCasesList` |
| Relevant principles | ✅ `ExperiencePanel` → `RelevantPrinciples` |
| **Senior-tip source chips + confidence badge** | ✅ **now** parsed in `SectionBlock` (`SeniorTip`) — was a raw line |
| **Principle provenance & verbatim quotes** | ✅ **now** `PrincipleRef` accordion → `ProvenanceList` (interview quotes + `ConfidenceBadge`) |

*Intentional differences (not regressions):* research is an explicit `/research`
skill rather than the Coach's auto-routed `isResearchQuestion` heuristic; the
English-mode "view JA original" translation-inspection toggle was dropped (the
JA source still grounds the answer server-side). Neither blocks removal.

---

## Key files

| File | Role |
|---|---|
| `web/components/workspace/workspace.tsx` | The shell — thread model (`WMsg`), `runChat`, `buildChatHistory`, in-place `onPick`, stop/clear, composer |
| `web/lib/artifacts.ts` | Artifact types + the three pure assemblers |
| `web/lib/artifact-export.ts` | Artifact → multi-sheet `.xlsx` serializer (`downloadArtifact`) |
| `web/components/workspace/slash.ts` | Explicit slash-command parsing |
| `web/components/workspace/artifact-card.tsx` | One-line dispatcher → `ArtifactBody` |
| `web/components/workspace/cards/artifact-body.tsx` | Unified renderer (`KIND_META`) |
| `web/components/assistant/message.tsx` | Shared `MessageBubble` + chat types (used by Workspace + Assistant) |
| `web/components/coach/similar-cases.tsx` | Shared Experience surface (`ExperiencePanel`) |
| `web/app/{junior,manager}/workspace/page.tsx` | Route loaders (role-scoped) |
