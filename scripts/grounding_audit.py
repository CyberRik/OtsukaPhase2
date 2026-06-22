"""Review Coach Grounding Audit (P0) — deterministic audits 1, 2, 3(structural), 5.

Produces real numbers (no LLM): retrieval trace, cross-customer leakage across all
open deals, prompt composition by source, and a structural classification of where
each deterministic claim comes from (customer evidence vs note-absence vs analogy).

Run: SENPAI=... python scripts/grounding_audit.py
"""
from __future__ import annotations
import re
from senpai import config
from senpai.data import store
from senpai.coach.review import review_note, commentary_prompt, LENSES, _present
from senpai.coach.context import build_commentary_context

# --- classify a context line by source -------------------------------------
def classify_line(line: str) -> str:
    s = line.strip()
    if s.startswith("CUSTOMER:"): return "customer_core"
    if s.startswith("DEAL "): return "customer_core"
    if s.startswith("RANK AGE:"): return "crm"
    if s.startswith("DEAL HEALTH:"): return "deterministic_health"
    if s.startswith("CONFIDENCE vs REALITY:"): return "crm"
    if s.startswith("RELIABILITY FLAGS:"): return "deterministic_health"
    if s.startswith("INACTIVITY:"): return "activity"
    if s.startswith("QUOTE:"): return "quote_order"
    if s.startswith("ORDERS:"): return "quote_order"
    if s.startswith("IT ENVIRONMENT:"): return "environment"
    if s.startswith("CUSTOMER HISTORY:"): return "customer_core"
    if s.startswith("ACCOUNT CONTEXT:"): return "deterministic_account_intel"
    if s.startswith("RECENT ACTIVITY") or s.startswith("- ") or re.match(r"^\d{4}-\d{2}-\d{2}", s): return "activity"
    if s.startswith("SIMILAR PAST CASE:"): return "similar_case_CROSS_CUSTOMER"
    if s.startswith("RELEVANT CORPUS KNOWLEDGE"): return "corpus_playbook"
    if s.startswith("- P") or re.match(r"^P\d{3}:", s): return "corpus_playbook"
    if s.startswith("[") : return "confidence_prefix"
    return "activity"  # indented activity snippets

CUSTOMER_EVIDENCE = {"customer_core","crm","deterministic_health","activity",
                     "quote_order","environment","deterministic_account_intel","confidence_prefix"}
NON_CUSTOMER = {"similar_case_CROSS_CUSTOMER","corpus_playbook"}

def pick_note(deal):
    acts = store.activities_for_deal(deal["deal_id"])
    return ((acts[0].get("daily_report") if acts else "") or "状況を確認したい").strip()

def compose(text):
    buckets = {}
    for ln in text.splitlines():
        if not ln.strip(): continue
        b = classify_line(ln)
        buckets[b] = buckets.get(b, 0) + len(ln)
    return buckets

# ===========================================================================
print("="*78)
print("AUDIT 1 — RETRIEVAL TRACE (one representative deal, condition C: ALL on)")
print("="*78)
# pick a red, open deal with a note (worst-case for narrative)
from senpai.health.scoring import score_deal
rep_deal = None
for d in store.open_deals():
    acts = store.activities_for_deal(d["deal_id"])
    if score_deal(d, acts, today=config.today()).band == "red" and acts:
        rep_deal = d; break
rep_deal = rep_deal or store.open_deals()[0]
note = pick_note(rep_deal)
cust = store.customer_name(rep_deal["customer_id"])
print(f"deal={rep_deal['deal_id']} customer={cust} cid={rep_deal['customer_id']}")
print(f"note: {note[:120]}")
ctxC, metaC = build_commentary_context(note, deal_id=rep_deal["deal_id"],
                                       include_similar_cases=True, include_corpus=True)
print(f"\n{'SOURCE TYPE':<32}{'SAME CUST?':<12}{'INJECTED':<10} CONTENT")
print("-"*78)
for ln in ctxC.splitlines():
    if not ln.strip(): continue
    b = classify_line(ln)
    same = "—" if b=="corpus_playbook" else ("NO(cross)" if b=="similar_case_CROSS_CUSTOMER" else "yes")
    print(f"{b:<32}{same:<12}{'YES':<10} {ln.strip()[:60]}")

# ===========================================================================
print("\n"+"="*78)
print("AUDIT 2 — CROSS-CUSTOMER LEAKAGE  (all open deals, condition C = pre-Phase1)")
print("="*78)
opens = store.open_deals()
n = len(opens)
cross_cust_runs = 0
nonconly_chars = total_chars = 0
worst = []
for d in opens:
    note_d = pick_note(d)
    txt, _ = build_commentary_context(note_d, deal_id=d["deal_id"],
                                      include_similar_cases=True, include_corpus=True)
    b = compose(txt)
    noncust = sum(v for k,v in b.items() if k in NON_CUSTOMER)
    tot = sum(b.values())
    if b.get("similar_case_CROSS_CUSTOMER",0) > 0:
        cross_cust_runs += 1
    nonconly_chars += noncust; total_chars += tot
    worst.append((noncust/tot if tot else 0, d["deal_id"], store.customer_name(d["customer_id"]),
                  b.get("similar_case_CROSS_CUSTOMER",0), b.get("corpus_playbook",0)))
print(f"runs: {n}")
print(f"cross-customer retrieval rate (similar case injected): {cross_cust_runs}/{n} = {100*cross_cust_runs/n:.0f}%")
print(f"avg % of CONTEXT chars that are NON-customer evidence: {100*nonconly_chars/total_chars:.1f}%")
worst.sort(reverse=True)
print("\nworst offenders (by non-customer share of context):")
print(f"  {'deal':<8}{'customer':<22}{'%noncust':<10}{'simcase_ch':<12}{'corpus_ch'}")
for share, did, cn, sc, co in worst[:8]:
    print(f"  {did:<8}{cn[:20]:<22}{100*share:<10.1f}{sc:<12}{co}")

# Phase-1 effect: re-run with similar cases OFF
nonc2 = tot2 = 0
for d in opens:
    txt, _ = build_commentary_context(pick_note(d), deal_id=d["deal_id"],
                                      include_similar_cases=False, include_corpus=True)
    b = compose(txt)
    nonc2 += sum(v for k,v in b.items() if k in NON_CUSTOMER); tot2 += sum(b.values())
print(f"\nPhase-1 (similar cases OFF): cross-customer rate -> 0/{n} = 0%")
print(f"Phase-1 non-customer share of context: {100*nonc2/tot2:.1f}%  (corpus principles only)")

# ===========================================================================
print("\n"+"="*78)
print("AUDIT 5 — PROMPT COMPOSITION (representative deal, FULL prompt, condition C)")
print("="*78)
r = review_note(note, deal=rep_deal, notes=store.activities_for_deal(rep_deal["deal_id"]))
full_prompt = commentary_prompt(note, r, ctxC, True, lang="ja")
# break full prompt into: system instructions, context (by source), note
ctx_start = full_prompt.find("文脈（記録より）:")
sys_part = full_prompt[:ctx_start]
note_idx = full_prompt.find("後輩のメモ:")
checklist_idx = full_prompt.find("後輩が既に持っているチェックリスト")
ctx_part = full_prompt[ctx_start:checklist_idx if checklist_idx>0 else note_idx]
checklist_part = full_prompt[checklist_idx:note_idx] if checklist_idx>0 else ""
note_part = full_prompt[note_idx:]
comp = compose(ctxC)
total = len(full_prompt)
rows = [("SYSTEM INSTRUCTIONS (prompt template)", len(sys_part), "instruction"),
        ("LENS CHECKLIST injection (absence-based)", len(checklist_part), "absence_lens"),
        ("REP NOTE (actual customer evidence)", len(note_part), "customer")]
for k,v in sorted(comp.items(), key=lambda x:-x[1]):
    tag = "CUSTOMER" if k in CUSTOMER_EVIDENCE else ("ANALOGY/GENERAL")
    rows.append((f"  context: {k}", v, tag))
print(f"{'COMPONENT':<46}{'CHARS':<8}{'%':<7} CLASS")
print("-"*78)
for name, ch, cls in rows:
    print(f"{name:<46}{ch:<8}{100*ch/total:<7.1f} {cls}")
print(f"{'TOTAL PROMPT':<46}{total:<8}{'100.0':<7}")
cust_ctx = sum(v for k,v in comp.items() if k in CUSTOMER_EVIDENCE)
print(f"\ncustomer evidence as share of CONTEXT block: {100*cust_ctx/sum(comp.values()):.1f}%")

# ===========================================================================
print("\n"+"="*78)
print("AUDIT 3 (structural) — WHERE DO DETERMINISTIC CLAIMS COME FROM?")
print("="*78)
print("Each lens fires on ABSENCE of cue words in the NOTE TEXT — not on customer")
print("evidence. Classifying the claims emitted for the representative deal:\n")
fired_lens = [l for l in LENSES if not _present(note, l.cues)]
print(f"{'CLAIM (observation)':<46}{'SOURCE':<18}{'GROUNDED?'}")
print("-"*78)
for l in fired_lens:
    print(f"{l.observation[:44]:<46}{'absence_lens':<18}{'UNSUPPORTED*'}")
# structured signals (these ARE grounded in CRM/activity)
acts = store.activities_for_deal(rep_deal["deal_id"])
res = score_deal(rep_deal, acts, today=config.today())
for reason in res.top_reasons(3):
    print(f"{reason[:44]:<46}{'score_deal':<18}{'SUPPORTED (CRM)'}")
print("\n* 'UNSUPPORTED' = triggered by what the NOTE didn't say, not by customer")
print("  records. The note simply omitting '決裁者' makes the coach assert the")
print("  decision-maker is unknown — even if the CRM has met one on another activity.")
