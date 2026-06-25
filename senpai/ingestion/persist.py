"""Persist an ingested daily report as a real `sales_activities` row.

Bridges the structured extraction (senpai.ingestion.multimodal.ActivityExtraction
/ the editable draft from `POST /api/ingest`) to the store. Produces a record in
the EXACT seed shape (see senpai/data/seed/sales_activities.json) so downstream
scoring/flags/retrieval read it like any other activity, then appends it to the
gitignored overlay via senpai.data.store.append_activity — the committed seed is
never mutated.

Fixes the three correctness gaps in the old pipeline.MultimodalIngestor demo:
  * fiscal_year/quarter use the Japanese fiscal calendar (config.fiscal_year_quarter)
  * department/division come from the rep record, not a mock
  * days_since_last_order/total_order_count derive from the customer's orders
"""
from __future__ import annotations

from senpai import config
from senpai.data import store

# The editable draft fields (must mirror ActivityExtraction / web ActivityDraft).
_DRAFT_FIELDS = (
    "activity_type", "business_card_info", "product_major_category",
    "customer_challenge", "daily_report",
)


def _order_stats(customer_id: str, activity_date: str) -> tuple[int, int]:
    """(days_since_last_order, total_order_count) from the customer's order
    history as of `activity_date`. Both 0 when the customer has no orders yet."""
    from datetime import date

    orders = store.orders_for_customer(customer_id)  # newest first
    total = len(orders)
    last = next((o.get("ordered_at") for o in orders if o.get("ordered_at")), None)
    if not last:
        return 0, total
    try:
        d0 = date.fromisoformat(last)
        d1 = date.fromisoformat(activity_date)
        return max(0, (d1 - d0).days), total
    except ValueError:
        return 0, total


def build_activity_record(
    draft: dict,
    customer_id: str,
    deal_id: str,
    employee_id: str,
) -> dict:
    """Map an edited draft to a full sales_activities record in seed shape."""
    deal = store.get_deal(deal_id) or {}
    rep = store.get_rep(employee_id) or {}

    activity_date = config.today().isoformat()
    fy, fq = config.fiscal_year_quarter(activity_date)
    dsl, toc = _order_stats(customer_id, activity_date)

    atype = draft.get("activity_type") or "002_Daily Report"
    return {
        "customer_id": customer_id,
        "opportunity_id": deal.get("opportunity_id", "OPP_UNKNOWN"),
        "fiscal_year": fy,
        "fiscal_quarter": fq,
        "started_at": deal.get("registered_at") or deal.get("started_at") or activity_date,
        "activity_date": activity_date,
        "closed_flag": False,
        "activity_type": atype,
        "days_since_last_order": dsl,
        "total_order_count": toc,
        "sales_info": {
            "department": rep.get("department", ""),
            "division": rep.get("division", ""),
            "employee_id": employee_id,
        },
        "business_card_info": draft.get("business_card_info", ""),
        "product_major_category": draft.get("product_major_category", ""),
        "customer_challenge": draft.get("customer_challenge", ""),
        "daily_report": draft.get("daily_report", ""),
        "quote_id": None,
        "order_id": None,
        "deal_id": deal_id,
    }


def save_activity(
    draft: dict,
    customer_id: str,
    deal_id: str,
    employee_id: str,
) -> dict:
    """Build the seed-shaped record and persist it to the overlay. Returns it."""
    record = build_activity_record(draft, customer_id, deal_id, employee_id)
    store.append_activity(record)
    return record
