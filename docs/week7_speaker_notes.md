# Speaker Notes — Senpai Weekly Progress Report (Phase 2, Week 3)

Keyed to the 12 slides in `docs/Senpai — Weekly Progress Report.pdf`. Each entry is a
script — say it close to as written. Bold lines are the soundbite: the one sentence that
should land if the audience remembers nothing else from that slide.

## The narrative spine

Right now the deck reads as twelve independent feature pitches. The fix isn't new
content, it's connective tissue: **three acts, one throughline, and two callbacks that
pay off a promise made early.**

- **Act 1 — The Platform Bet (slides 3-4).** We rebuilt the foundation. The claim to
  prove: we did it without breaking anything.
- **Act 2 — Stress-Tested Against Reality (slides 5-8).** We built new things on that
  foundation, pointed real customer names at them, and hardened what broke.
- **Act 3 — Why You Can Trust It, and What's Next (slides 9-12).** The actual mechanism
  that makes "the model never lies about a number" true, extended to a second audience
  (managers), plus an honest look at what's left.

The throughline underneath all three acts is **trust, earned mechanically, not claimed
verbally** — say a version of that sentence at the top (slide 1) and again at the close
(slide 12) so it bookends the talk.

**The two callbacks to set up and pay off:**
1. Slide 2 says "the model never invents an ID or a number" — plant it as a promise
   ("I'll show you exactly where that's enforced"). Slide 9 pays it off (the citation
   firewall). Slide 10 pays it off again at the aggregate level (the grounding gate).
   When you hit slide 9, say "remember the promise from the principles slide — here's
   the code that keeps it."
2. Slide 2 also says "correct without the model, better with it" — plant it. Slide 5
   pays it off (heuristic fallback when the model server is down). Slide 9 pays it off
   again (automatic failover). Naming the callback out loud ("this is principle two,
   playing out again") is what turns five separate 'nice, it degrades gracefully'
   moments into one deliberate design philosophy in the audience's head.

Don't announce "Act 1" as jargon — say the plain-English version once at the start
(below) and let the section breaks in the actual talk carry it.

---

## Slide 1 — Title

"Week 2 turned the prototype into a product. This week we turned the product into a
platform. And underneath it all, we fundamentally upgraded our inference engine — leveraging prefix caching and transitioning to an fp4 Atlas format to slash GPU usage and make generation lightning fast. 

I want to show you three things today: first, that this massive backend rebuild held together with
zero regressions; second, what we built on top of it and what broke the moment we pointed
real customer names at it instead of test data; and third — the part I actually think
matters most — the specific mechanics that let us say, honestly, that this system doesn't
lie to a customer about a number. Let's start with the rules we don't break."

---

## Slide 2 — Guiding Principles

"These five rules aren't a mission statement, they're enforced in code. Two of them
matter most, and I'm going to come back to both of them later, so hold onto these:
**one — the model never invents an ID or a number**, there's a firewall downstream that
deletes anything it can't prove, and I'll show you exactly where that lives. **Two — this
is correct without the model, and better with it** — if our GPU server goes down
completely, the system doesn't go down with it, it falls back to deterministic logic and
keeps answering correctly. Keep those two in your head. Now let's go build on top of
them."

---

## Slide 3 — Orchestration Engine (Section 1 · Flagship)

"Here's the foundation everything else this week sits on. Every feature we ship —
Research, Crew, Account intelligence, Chat — used to be its own separate 'go gather data
then answer' codebase. Four places to fix the same bug. This quarter we collapsed all four
onto one engine. **Write one capability, register it, and it gets parallel execution,
retry safety, and graceful degradation for free.** 

To make this system extremely fast, our Adaptive Scheduler builds an Execution Plan (DAG) that intelligently distinguishes between read and write operations. It aggressively groups safe reads to run concurrently on a threaded engine, while automatically inserting serialization barriers for unsafe writes to prevent race conditions. The engine also supports dynamic DAG expansion — meaning a single task can spawn parallel sub-tasks autonomously, saving us from waiting on round-trips to the LLM.

And if one step fails, the engine doesn't crash the whole answer — it isolates the failure, handles retries, and returns what it has. That's the bet: one fast, resilient spine, not four. Now watch what it cost us to prove that bet didn't break anything."

---

## Slide 4 — Migration Milestones M0–M6

"We didn't rewrite this and hope. Every migration step was gated by a parity test — the
new path had to match the old path exactly, on real cases, before we were allowed to
delete the old code. Research: 84 cases. Account: 123, because this product runs
bilingually end to end. **Zero regressions the entire way — 219 tests, then 282, then 405,
every one still green.** That's act one: we rebuilt the engine room without anyone
noticing from the deck. Act two is what we built with it — starting with the feature that
turns a chat message into a finished document."

---

## Slide 5 — LLMPlanner (Section 2)

"Watch this: a rep types 'make me a proposal for Murata Printing' — no slash command, no
special syntax. **The model's only job is to pick which capability to run. It never
touches the customer ID.** Deterministic code resolves who Murata Printing actually is, so
a name collision can't silently become the wrong company's proposal. And remember
principle two from the start — correct without the model? Here it is again: if the model
server is down entirely, this still works, because there's a deterministic fallback
underneath it. One goal, one plan, one document — every time. That predictability is what
let us point this at a second, riskier surface next: a rep's actual files."

---

## Slide 6 — Local Workspace Agent (Section 3)

"This is the first time Senpai touches something outside our seed database — a rep's real
local files. Riskier surface, so we built the safety rails first: everything sandboxed to
one folder, no delete operation anywhere in this capability — deliberate, not missing —
and any reorganization shows you the plan and waits for 'go ahead' before touching
anything. **The worst thing this feature can do is put a file in the wrong folder. It can
never lose one.** That's two new capabilities shipped clean. Now the honest part of the
talk: here's what broke when we stopped testing against demo data and started testing
against real customer names."

---

## Slide 7 — Smart Tool-Calling & Loop Prevention (Section 4 · Reliability)

"Give an LLM a tool loop and it will happily burn ten rounds re-asking the same empty
question. We capped that — two unproductive rounds on the same tool and it stops — but ask
about three *different* deals at once and that's real work, not a spiral, so it's exempt.
Once a proposal actually generates, the loop hard-stops, which is the specific thing
preventing two PPTX files for one request. And a number worth remembering: **comparing
three deals dropped from 75 seconds to 28**, because we detect the multi-deal ask up front
and gather everything in parallel instead of one round-trip at a time. That's reliability
under load. The next bug was quieter, and arguably worse, because it was silent."

---

## Slide 8 — Context & Memory Management (Section 5 · Context)

"Here's the bug, in plain language: you say 'make a proposal for the company I just
mentioned,' and the background job generating that document literally couldn't see the
chat you'd just had — so it hallucinated a generic deck for nobody. **Fixed: the
conversation is now safely shared with every background task, without leaking between two
reps' conversations happening at the same time.** We also made memory relevant, not just
recent, and made sure the system only locks onto a company by a real confirmed ID, never a
fuzzy name match — which is exactly what stops it confusing 村田 with an unrelated 松田
account. That closes act two — everything we built, and everything real usage broke and we
fixed. Now, the part I actually think matters most: how do we know it won't just make
something up?"

---

## Slide 9 — Two-Pass Reasoner & Dual-Model Foundation (Section 6-7 · Reasoning & Model)

"Remember the promise from the principles slide — the model never invents a number? Here's
the code that keeps it. The model writes a claim and attaches the evidence it's based on.
Then our code checks every citation, and if it doesn't trace back to real evidence, **we
delete the claim. Not flag it — delete it, before it ever reaches a customer.** And
principle two, paying off one more time: cheap tasks go to a small fast model,
quality-critical narrative goes to our larger model, and if either server drops, we fail
over automatically — no crashed conversation. Every token is logged, clearly marked
measured or estimated, so any cost number we report is one we can stand behind. That's the
mechanism behind the promise. Now let's take it somewhere a single deal record can't
go — a manager's question."

---

## Slide 10 — Segment Intelligence / GraphRAG (Section 8 · GraphRAG)

"A manager asks 'why do we keep losing manufacturing server deals' — no single deal record
answers that, you need a rollup across all of them. **Same rule as the reasoner, applied
at the aggregate level: every number a summary could use is pre-computed and whitelisted,
and if the writeup contains a figure that isn't on that list, we throw it out and fall
back to a plain, guaranteed-accurate sentence instead.** We also skip the expensive part of
a typical GraphRAG pipeline entirely, because our CRM data is already a clean structured
graph — nothing to extract from raw text. That's the trust machinery, proven twice, at two
different altitudes. Last two slides: the unglamorous work, and what's next."

---

## Slide 11 — Product Foundation (Section 9 · Product)

"I'll say this one plainly: nothing here is a headline feature. But **login, persistent
chat history, and one home screen instead of six** are what make this something a real
team adopts, not just watches us demo. Every account maps to a real seed rep, chat history
now survives a page refresh and is searchable, and the six pages a junior rep used to
bounce between are one screen now. Unglamorous, necessary, done. Last slide."

---

## Slide 12 — Roadmap

"**Next milestone is expansion, not rewrite** — say it exactly like that, it's the line
that ties the whole talk together. Meeting-prep and account-intelligence become new
LLMPlanner capabilities on the exact same engine we parity-tested in act one — no new
infrastructure. We're wiring in the read side of cross-chat memory so past conclusions
actually get used, not just stored. And one thing I want to be upfront about rather than
have someone find later: we've got four separate reasoner implementations right now, and
converging them onto one is scheduled cleanup, not something we're hoping nobody notices.
We rebuilt the foundation, we stress-tested it against real names, and we can now show you
exactly why it won't lie to a customer. That's the week."
