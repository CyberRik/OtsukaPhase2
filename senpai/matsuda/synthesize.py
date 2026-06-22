from __future__ import annotations

from datetime import date

from senpai import config
from senpai.data import store
from senpai.health import scoring, flags
from senpai.retrieval.playbook import retrieve_playbook, find_similar_deals
from senpai.matsuda.context import DealView, AccountContext

def build_account_context(customer_id: str) -> AccountContext:
    """Synthesizes all available information about the specified customer 
    into a single AccountContext."""
    store.reload() # Ensure fresh data
    today = config.today()
    
    customer = store.get_customer(customer_id)
    if not customer:
        raise ValueError(f"Customer {customer_id} not found")
        
    environment = store.get_environment(customer_id)
    retrieval_log = [
        ("store", f"Customer {customer_id}", 1),
        ("store", f"Environment {customer_id}", 1 if environment else 0)
    ]
    
    all_activities = [a for a in store.all_activities() if a.get("customer_id") == customer_id]
    all_activities.sort(key=lambda x: x.get("activity_date", ""), reverse=True)
    retrieval_log.append(("store", f"Activities for {customer_id}", len(all_activities)))
    
    # Extract decision makers
    dm_titles = set()
    for act in all_activities:
        card = act.get("business_card_info") or ""
        for title in config.DECISION_MAKER_TITLES:
            if title in card:
                dm_titles.add(title)
                
    raw_deals = [d for d in store.all_deals() if d.get("customer_id") == customer_id and config.is_open_rank(d.get("order_rank"))]
    retrieval_log.append(("store", f"Open Deals for {customer_id}", len(raw_deals)))
    
    deal_views = []
    owner_ids = set()
    product_codes_used = set()
    product_to_deals = {}
    
    for d in raw_deals:
        deal_id = d["deal_id"]
        acts = [a for a in all_activities if a.get("deal_id") == deal_id]
        
        health = scoring.score_deal(d, acts, today)
        fls = flags.deal_flags(d, acts, health_band=health.band, today=today)
        
        rep_id = store.deal_rep_id(d)
        rep = store.get_rep(rep_id) or {}
        owner_ids.add(rep_id)
        
        p_codes = d.get("products", [])
        p_names = []
        for pc in p_codes:
            product_codes_used.add(pc)
            if pc not in product_to_deals:
                product_to_deals[pc] = []
            product_to_deals[pc].append(deal_id)
            p = store.get_product(pc)
            if p:
                p_names.append(p["product_name"])
                
        last_contact = next((a.get("activity_date") for a in acts if a.get("activity_date")), None)
        
        dv = DealView(
            deal_id=deal_id,
            name=d.get("deal_name", ""),
            rank=d.get("order_rank", ""),
            amount=d.get("total_order_amount", 0),
            owner_id=rep_id,
            owner_name=rep.get("name", ""),
            owner_role=rep.get("role", ""),
            owner_specialties=rep.get("specialty_tags", []),
            product_codes=p_codes,
            product_names=p_names,
            band=health.band,
            score=health.score,
            reasons=health.top_reasons(3),
            flags=[f.message for f in fls],
            has_decision_maker=scoring._has_decision_maker(acts),
            last_contact=last_contact,
            expected_order_date=d.get("expected_order_date"),
            activity_count=len(acts)
        )
        deal_views.append(dv)
        
    reps = [store.get_rep(r) for r in owner_ids if store.get_rep(r)]
    retrieval_log.append(("store", f"Reps on account", len(reps)))
    
    products = []
    for pc in product_codes_used:
        p = store.get_product(pc)
        if p:
            p_copy = dict(p)
            p_copy["deal_ids"] = product_to_deals[pc]
            products.append(p_copy)
    retrieval_log.append(("store", f"Products", len(products)))
            
    # Similar Deals
    similar = find_similar_deals(customer_id=customer_id, limit=5)
    enriched_similar = []
    for sd in similar:
        sd_copy = dict(sd)
        c = store.get_customer(sd["customer_id"]) or {}
        sd_copy["customer_name"] = c.get("name", "Unknown")
        sd_copy["industry"] = c.get("industry", "Unknown")
        sd_copy["size"] = c.get("size", "Unknown")
        enriched_similar.append(sd_copy)
        
    won_similar = [sd for sd in enriched_similar if sd.get("order_rank", "").startswith("1_")]
    retrieval_log.append(("retrieval", "Similar Deals", len(enriched_similar)))
    retrieval_log.append(("retrieval", "Won Similar Deals", len(won_similar)))
    
    # Playbook
    # Collect tags from customer profile and bad health signals
    playbook_tags = set(customer.get("profile_tags", []))
    for dv in deal_views:
        if dv.band in ("red", "yellow"):
            # Attempt to map risk to playbook tags
            if "決裁" in "".join(dv.reasons):
                playbook_tags.add("決裁者")
            if "停滞" in "".join(dv.reasons) or "接触なし" in "".join(dv.reasons):
                playbook_tags.add("停滞")
            
    playbook = retrieve_playbook(tags=list(playbook_tags), limit=3)
    retrieval_log.append(("retrieval", "Playbook entries", len(playbook)))
    
    # Next actions synthesis
    next_actions = []
    at_risk = sorted([dv for dv in deal_views if dv.band != "green"], key=lambda dv: dv.score, reverse=True)
    if at_risk:
        worst = at_risk[0]
        if not worst.has_decision_maker:
            next_actions.append(f"【最優先】要注意案件 {worst.deal_id}（{worst.name}）の決裁者を特定し、アプローチする。")
        else:
            next_actions.append(f"【最優先】要注意案件 {worst.deal_id}（{worst.name}）の停滞要因（{worst.reasons[0]}）を解消する。")
            
    missing_dm_deals = [dv for dv in deal_views if not dv.has_decision_maker and dv != (at_risk[0] if at_risk else None)]
    if missing_dm_deals:
        next_actions.append(f"決裁者が未登録の案件（{missing_dm_deals[0].deal_id} など）について、役職者への接触を図る。")
        
    if not next_actions:
        next_actions.append("すべての案件が順調です。引き続き現在のペースでフォローしてください。")
        
    return AccountContext(
        built_at=today,
        customer=customer,
        environment=environment,
        reps=reps,
        deals=deal_views,
        activity_timeline=all_activities,
        products=products,
        similar_deals=enriched_similar,
        won_similar_deals=won_similar,
        playbook=playbook,
        next_actions=next_actions,
        decision_maker_titles=list(dm_titles),
        retrieval_log=retrieval_log
    )
