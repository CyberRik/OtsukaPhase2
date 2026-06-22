"""Audit 4 — Similar-Case Contamination Test (A/B/C) with the live model.

Same deal/note, three retrieval conditions:
  A  customer evidence only      (similar OFF, corpus OFF)
  B  + playbooks                 (similar OFF, corpus ON)
  C  + similar cases             (similar ON,  corpus ON)
NOTE: the absence-lens checklist is injected by commentary_prompt in ALL three,
so it is the constant baseline; A/B/C isolate the retrieval (analogy) effect.
"""
from __future__ import annotations
import re
from senpai import config
from senpai.data import store
from senpai.coach.review import review_note, commentary_prompt
from senpai.coach.context import build_commentary_context
from senpai.llm import client
from senpai.health.scoring import score_deal

did = "D001"
deal = store.get_deal(did)
acts = store.activities_for_deal(did)
note = (acts[0].get("daily_report") or "状況を確認したい").strip()
r = review_note(note, deal=deal, notes=acts)

SPEC = ["likely","probably","おそらく","可能性","かもしれ","と思われ","推測","はず","だろう","may ","might "]

def run(label, sim, corp):
    ctx, _ = build_commentary_context(note, deal_id=did, lang="ja",
                                      include_similar_cases=sim, include_corpus=corp)
    prompt = commentary_prompt(note, r, ctx, True, lang="ja")
    out = ""
    for p in client.stream_complete([{"role":"user","content":prompt}],
                                     temperature=0.5, max_tokens=config.LLM_NARRATE_MAX_TOKENS,
                                     no_think=True, allow_fallback=False):
        out += p
    out = re.sub(r"<think(?:ing)?>.*?</think(?:ing)?>", "", out, flags=re.DOTALL).strip()
    spec = sum(out.lower().count(s.lower()) for s in SPEC)
    # cross-customer name leak: does another customer's name appear?
    others = [store.customer_name(d["customer_id"]) for d in store.all_deals()
              if d["customer_id"] != deal["customer_id"]]
    leak = sorted({o for o in others if o and o in out})
    print(f"\n{'='*78}\nCONDITION {label}  (similar={sim}, corpus={corp})  chars={len(out)} "
          f"speculative_terms={spec} cross_cust_names={leak}\n{'='*78}")
    print(out)
    return out

print(f"deal={did} customer={store.customer_name(deal['customer_id'])} "
      f"band={score_deal(deal,acts,today=config.today()).band}")
print(f"note: {note}")
a = run("A", False, False)
b = run("B", False, True)
c = run("C", True,  True)
