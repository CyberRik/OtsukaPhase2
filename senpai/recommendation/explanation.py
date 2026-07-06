"""LLM explanation layer for recommendations.

The LLM is constrained to narrating and prioritizing a deterministic candidate set
provided to it. It NEVER invents candidates.
"""
from __future__ import annotations

import json
from typing import Any, Mapping

from senpai.llm.client import simple_complete
from senpai.orchestration.evidence import EvidenceBundle
from senpai.orchestration.reason import _extract_json_array, known_citations
from senpai.recommendation.candidate import Candidate
from senpai.recommendation.schema import Recommendation


_EXPLAIN_SYSTEM = """You are a senior B2B solutions consultant for Otsuka.
You are given an evidence bundle about a customer (CRM data, activity, etc.) and a
CLOSED LIST of solution candidates that have already been deterministically selected
based on category and expansion signals.

Your job is to explain WHY each candidate is recommended for this specific customer,
evaluate its business value, identify any risks, and suggest questions to ask.

CRITICAL RULES:
1. You may ONLY output information for the exact candidates provided in the list.
   DO NOT invent new solutions or recommend anything not on the list.
2. Every explanation MUST cite the evidence handle(s) it rests on (e.g., "SPR D003",
   "Playbook PB12"). Use the exact strings from the evidence.
3. Return ONLY a JSON array of objects, one for each candidate.
   No prose outside the JSON array.

Expected JSON schema per object:
{
  "id": "string (MUST exactly match the candidate id)",
  "confidence": "number (0.0 to 1.0, your confidence in this recommendation)",
  "why": "string (Why it fits this customer, MUST cite evidence)",
  "evidence": ["string (citation handles used)"],
  "business_value": "string (Value proposition for the customer)",
  "risks": ["string (Any risks or blockers)"],
  "questions_to_ask": ["string (Questions to qualify the opportunity)"],
  "complementary_solutions": ["string (Names of related solutions, if any)"]
}
"""


def explain_candidates(bundle: EvidenceBundle, candidates: list[Candidate],
                       max_tokens: int = 1500) -> list[Recommendation]:
    """Take a deterministic candidate set and an EvidenceBundle, and use the LLM to
    build the narrative fields (why, business_value, etc.), returning structured
    Recommendation objects. Uncited claims or invented candidates are dropped."""
    
    if not candidates:
        return []

    # 1. Build the input view
    # We give the LLM the reasoner view of the evidence, and the CLOSED list of
    # candidate IDs and names.
    allowed_citations = known_citations(bundle.to_reasoner_view())
    
    candidate_refs = [
        {
            "id": c.id,
            "title": c.title,
            "match_score": c.match_score,
            "reasons": c.reasons,
        }
        for c in candidates
    ]
    
    payload = {
        "evidence_bundle": bundle.to_reasoner_view(),
        "candidates": candidate_refs,
    }

    prompt = ("Customer Evidence and Candidates (JSON):\n"
              + json.dumps(payload, ensure_ascii=False, indent=2))

    # 2. Invoke the LLM
    try:
        raw = simple_complete(
            [{"role": "system", "content": _EXPLAIN_SYSTEM},
             {"role": "user", "content": prompt}],
            temperature=0.0, max_tokens=max_tokens,
            no_think=True, allow_fallback=False,
        )
    except Exception:
        # Fallback to empty explanations if the LLM fails
        raw = "[]"

    # 3. Parse and enforce constraints
    arr = _extract_json_array(raw) or []
    
    # Map the LLM output by candidate id
    explanations = {
        str(item.get("id")): item
        for item in arr
        if isinstance(item, dict) and item.get("id")
    }
    
    recommendations = []
    
    for c in candidates:
        expl = explanations.get(c.id) or {}
        
        # Firewall: keep only citations the evidence actually provided.
        raw_cites = expl.get("evidence") or []
        if isinstance(raw_cites, str):
            raw_cites = [raw_cites]
        
        valid_cites = tuple(
            cite for cite in raw_cites 
            if isinstance(cite, str) and cite in allowed_citations
        )
        
        # The LLM's explanation MUST be grounded. If it cited nothing valid,
        # we still return the recommendation (since the candidate is deterministically
        # valid) but we strip the hallucinated "why".
        why = str(expl.get("why") or "")
        if why and not valid_cites:
            why = ""
            
        try:
            confidence = max(0.0, min(1.0, float(expl.get("confidence", 0.5))))
        except (TypeError, ValueError):
            confidence = 0.5
            
        business_value = str(expl.get("business_value") or "")
        
        risks = expl.get("risks") or []
        if isinstance(risks, str):
            risks = [risks]
        risks = tuple(str(r) for r in risks)
        
        questions_to_ask = expl.get("questions_to_ask") or []
        if isinstance(questions_to_ask, str):
            questions_to_ask = [questions_to_ask]
        questions_to_ask = tuple(str(q) for q in questions_to_ask)
        
        complementary = expl.get("complementary_solutions") or []
        if isinstance(complementary, str):
            complementary = [complementary]
        complementary = tuple(str(comp) for comp in complementary)
        
        # Merge deterministic fields from the Candidate with narrative fields from the LLM
        # product_pages is built from the candidate's payload
        url = c.payload.get("url") or c.id
        title = c.payload.get("title") or c.title
        product_pages = ({"title": title, "url": url},)
        
        category = c.payload.get("category") or "Unknown"

        # Determine status based on reasons
        status = "recommended"
        if any("already_owned" in r for r in c.reasons):
            status = "already_owned"
            
        # Optional fallback if no why was generated
        if not why:
            why = f"Deterministically recommended based on: {', '.join(c.reasons)}"
            
        rec = Recommendation(
            solution_name=c.title,
            category=category,
            match_score=c.match_score,
            confidence=confidence,
            why=why,
            evidence=valid_cites,
            product_pages=product_pages,
            business_value=business_value,
            risks=risks,
            complementary_solutions=complementary,
            status=status
        )
        recommendations.append(rec)
        
    return recommendations
