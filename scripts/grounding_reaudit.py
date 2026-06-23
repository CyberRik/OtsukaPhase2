"""Grounding re-audit — measure the P0 fixes against a baseline (needs the model).

Per deal, generate commentary two ways on identical grounded context:
  BASELINE  the old speculative 4-angle prompt (reconstructed here, not prod)
  GROUNDED  the new 3-section Known-Facts / Open-Questions / Prep prompt (prod)

Automatable metrics per output:
  speculative_terms        count of hedging/speculation tokens
  cross_customer_refs       other customers' names that leaked in
  out_of_context_principles principle ids cited but NOT present in the context
  has_three_sections        the grounded structure was followed

Aggregate: unsupported-claim proxy, fabricated-customer-reference rate, grounding
quality (= clean outputs / total). Run when :8765 is back:
  SENPAI_USE_LLM=1 PYTHONUTF8=1 PYTHONPATH=. python scripts/grounding_reaudit.py
"""
from __future__ import annotations
import os, re
from senpai import config
from senpai.data import store
from senpai.coach.review import review_note, commentary_prompt
from senpai.coach.context import build_commentary_context
from senpai.llm import client
from senpai.health.scoring import score_deal

N = int(os.environ.get("REAUDIT_N", "15"))
SPEC = ["likely","probably","おそらく","可能性","かもしれ","と思われ","推測","はず","だろう",
        "must be","may be","might"]
PRIN = re.compile(r"P\d{3}")
ALL_CUST = {store.customer_name(d["customer_id"]) for d in store.all_deals()}

def baseline_prompt(note, ctx):  # the OLD speculative style, for contrast only
    return ("あなたは経験豊富な営業マネージャーです。状況をどう読むか率直に伝え、"
            "顧客側で起きていそうな力学（社内検討・予算・優先順位）も推測してよい。\n\n"
            f"文脈:\n{ctx}\n\n後輩のメモ:\n{note}")

def gen(prompt):
    out = ""
    for p in client.stream_complete([{"role":"user","content":prompt}], temperature=0.5,
                                    max_tokens=config.LLM_NARRATE_MAX_TOKENS,
                                    no_think=True, allow_fallback=False):
        out += p
    return re.sub(r"<think(?:ing)?>.*?</think(?:ing)?>","",out,flags=re.DOTALL).strip()

def measure(out, subject, ctx):
    spec = sum(out.lower().count(s.lower()) for s in SPEC)
    leaks = sorted({c for c in ALL_CUST if c and c != subject and c in out})
    cited = set(PRIN.findall(out)); in_ctx = set(PRIN.findall(ctx))
    oop = sorted(cited - in_ctx)
    secs = sum(h in out for h in ("確認できている事実","確認すべき問い","準備の提案"))
    return dict(spec=spec, leaks=leaks, oop=oop, secs=secs, n=len(out))

def run():
    deals = [d for d in store.open_deals()
             if score_deal(d, store.activities_for_deal(d["deal_id"]),
                           today=config.today()).band in ("red","yellow")][:N]
    agg = {"BASELINE": [], "GROUNDED": []}
    for d in deals:
        did=d["deal_id"]; acts=store.activities_for_deal(did)
        note=(acts[0].get("daily_report") or "状況確認").strip()
        subj=store.customer_name(d["customer_id"])
        r=review_note(note, deal=d, notes=acts)
        ctx,meta=build_commentary_context(note, deal_id=did, lang="ja")
        b=gen(baseline_prompt(note,ctx)); g=gen(commentary_prompt(
            note,r,ctx,meta["has_customer_context"],lang="ja",
            customer_name=subj,deal_id=did))
        mb=measure(b,subj,ctx); mg=measure(g,subj,ctx)
        agg["BASELINE"].append(mb); agg["GROUNDED"].append(mg)
        print(f"{did} {subj[:14]:<14} BASELINE spec={mb['spec']} leaks={len(mb['leaks'])} oop={len(mb['oop'])}"
              f" | GROUNDED spec={mg['spec']} leaks={len(mg['leaks'])} oop={len(mg['oop'])} secs={mg['secs']}/3")
    print("\n=== AGGREGATE (n=%d) ===" % len(deals))
    for cond in ("BASELINE","GROUNDED"):
        m=agg[cond]; n=len(m) or 1
        spec=sum(x['spec'] for x in m)/n
        fab=sum(1 for x in m if x['leaks'] or x['oop'])/n
        clean=sum(1 for x in m if not x['spec'] and not x['leaks'] and not x['oop'])/n
        print(f"{cond:<9} avg_speculative_terms={spec:.2f}  fabricated_ref_rate={100*fab:.0f}%  "
              f"grounding_quality(clean)={100*clean:.0f}%")

if __name__ == "__main__":
    run()
