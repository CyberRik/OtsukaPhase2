# Senpai — Knowledge Extraction from Limited Interviews

We have **2 senior respondents**, each answering the same **7 forced-choice
scenarios** with their reasoning (A/B + なぜ). That is 14 tacit-judgment data
points, not "2 thin interviews." This doc turns them into validated principles
and onboarding scenarios — with provenance preserved at every step.

The key unlock: a forced-choice + *reasoning* format exposes the **decision
factor** behind each choice. Two seniors reasoning over the same dilemma gives us
three gifts at once:
- **Agreement** → a high-confidence principle (2 independent sources).
- **Divergence** → a built-in *alternative viewpoint* (teaches judgment, not rules).
- **The "why"** → the decision factor a junior can't see yet.

---

## 1. Principle Extraction Worksheet (reusable)

Fill one card per principle. One scenario can yield 1–2 principles.

```
┌─ PRINCIPLE CARD ────────────────────────────────────────────────┐
│ Principle      : <one validated claim, in the senior's own logic> │
│ Supporting     : "<verbatim quote>"   (source: R1/R2, Qn)         │
│   quote(s)       "<verbatim quote>"   (source: R1/R2, Qn)         │
│ Reasoning      : <the mental model — "X because Y leads to Z">     │
│   pattern                                                          │
│ Decision       : <what should tip the choice: relationship, budget,│
│   factors        stakeholder, timing, certainty…>                 │
│ Warning        : <what a senior treats as a red flag here>        │
│   signals                                                          │
│ Questions      : <what the senior asks to resolve the situation>  │
│   asked                                                            │
│ Alternative    : <when the opposite choice is right, and why>     │
│   viewpoints     (often = the OTHER respondent's reasoning)       │
│ Tags           : <align to Coach lens tags: 決裁者未特定, 予算, … >│
│ Support count  : 1 source = low/medium · 2 sources = high         │
└──────────────────────────────────────────────────────────────────┘
```

**Rule:** the *Principle*, *Decision factors*, *Warning signals* and *Questions*
must be paraphrases of what the source actually said. Anything you can't tie to a
quote is a hypothesis — park it as `status: candidate`, do not promote it.

---

## 2. Process: 2 interviews → 10–20 validated principles

1. **Atomise.** Read each answer. Each *reason clause* ("～だから", "～ため") is a
   candidate principle. 2 respondents × 7 scenarios ≈ 14 reason clauses → start
   with ~14 candidates.
2. **Merge agreements.** Where both respondents give the same reasoning for the
   same scenario, merge into ONE principle citing **both** quotes → high
   confidence. (Here: scenarios 1, 4, 5, 7.)
3. **Split divergences.** Where they choose differently, you usually have *one*
   principle + an *alternative viewpoint* (conditional on relationship / budget /
   stakeholder). Capture both — do not average them away.
4. **Mine the second clause.** Long answers contain two ideas (e.g. R2-Q4 =
   "don't ignore IT" *and* "reduce migration load first"). Each becomes its own
   principle, citing a different span of the same answer.
5. **Stop at validated.** With this data you get **~11 strong principles**; reach
   15–20 only by promoting the conditional sub-principles (the A-vs-B branches) to
   their own cards. Never pad with un-sourced "best practice."
6. **Hand to a human.** Principles stay `candidate` until the PM / a senior
   confirms each card against the transcript, then flips it to `approved`.

**Yield from this dataset: 11 principles, 4 with two-respondent agreement.** See §4.

---

## 3. Process: principle → onboarding content (provenance preserved)

Each approved principle expands into Layer-2 *items* the Sales Review Coach shows.
GenAI (or a human curator) may only **illustrate** the principle:

```
APPROVED PRINCIPLE  (carries: statement + quotes + interview_ids)
        │  generate.py  — prompt = principle ONLY, forbid new advice/numbers
        ▼
DRAFT ITEM { scenario, signals, risks, coaching questions, alternatives }
        │  ground_check() — reject invented specifics / missing alternatives
        ▼
HUMAN REVIEW  (approve / edit / reject)  — knowledge_review.py console
        ▼
COACH surfaces it as: 先輩の知見 (出典 I01・I02 / 確度 high)
```

Provenance is never broken: every item stores `principle_id`, `interview_ids`,
`generator_model`, `prompt_version`, `grounding_passed`, and the reviewer.
Confidence is **recomputed from the backing principle at approval time** — 2
interviews → high, 1 → low/medium. You cannot hand-author a "high".

### Worked expansion (P008 — 初回訪問は関係構築優先, 2-source → high)

> **Scenario**: 新人が初回訪問でいきなり「PCは何台？OSは？」と環境ヒアリングを始めたが、担当者の口が重く情報を引き出せなかった。
> **Signals**: 担当者の反応が浅い／環境の質問に具体的な答えが返らない／関係がまだ築けていない
> **Risks**: 初回から情報収集に走ると警戒され、以降の関係構築が難しくなる
> **Coaching questions**: 御社の業務で今いちばんお困りのことは？／普段どんな場面でPC・ネットワークをお使いですか？
> **Alternatives**: 既存の信頼があり時間が限られる再訪問なら、環境確認を先に進めてよい場合もある
> **Provenance**: P008 ← R1-Q5「ただ環境を聞くだけでは教えてもらえない」+ R2-Q5「初回は関係構築が最重要…業務内容や関心事をヒアリング」

This item ships in `generated_items.json` (status `draft`) ready to approve.

---

## 4. The extracted principles (loaded into `knowledge/seed/principles.json`)

R1 = respondent A (interview `I01`), R2 = respondent B (`I02`). All `candidate`
until you approve them in the review console.

| ID | Principle | Sources | Conf. (after approval) |
|----|-----------|---------|------|
| P001 | 新しい提案で間口を広げる前に、今の案件の確度と決定時期を白黒つける | R1-Q1 + R2-Q1 | **high** |
| P002 | 値引きは最終手段。安易に価格カードを切らない | R1-Q2 | low |
| P003 | 担当者の「〜かもしれない」だけで動かず、キーマンに会って事実を確認してから方針を決める | R2-Q2 | low |
| P004 | 最初から妥協策を出さず、まず本命(A)を試し、通らなければ次善(B)に切替える | R1-Q3 | low |
| P005 | 予算の確保が案件進行の前提。資金の目処が立つまで早期クロージングを押さない | R2-Q3 | low |
| P006 | 決裁者(部長)はIT担当者が納得しないと契約に踏み切らない。現場の技術担当を味方につける | R1-Q4 + R2-Q4 | **high** |
| P007 | 技術部門を軽視すると将来の取引に響く。専門MTGの前に移行負荷を下げる提案を決裁者へ | R2-Q4 | low |
| P008 | 初回訪問は情報収集より関係構築。スペックより業務・関心をヒアリング | R1-Q5 + R2-Q5 | **high** |
| P009 | 競合を貶めない。他社を下げる発言は逆効果 | R1-Q6 | low |
| P010 | 決めるのはお客様。選定基準を先に確認し、その基準に合わせて価値を示す | R2-Q6 | low |
| P011 | 決裁者同席の依頼はタイミングと関係性で判断。急な依頼は「蔑ろにされた」と逆効果 | R1-Q7 + R2-Q7 | **high** |

**Demo headline:** *"From 2 surveys we validated 11 senior principles — 4 backed by
both seniors independently — every one traceable to the exact sentence a senior
wrote."* That is the anti-synthetic story.

### How to reach 15–20 (only if you want the count)
Promote each two-respondent **divergence** into its own conditional card, e.g.
P011 splits into:
- P011a「関係が良ければ早めに決裁者同席を依頼し工数を減らす」(R2-Q7, branch A)
- P011b「関係が浅ければ担当者を立て、段階を踏んでから同席を打診」(R1-Q7 + R2-Q7, branch B)

Each is still 100% sourced. Do this for scenarios 3, 6, 7 → +4–6 principles.
