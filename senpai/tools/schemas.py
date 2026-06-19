"""OpenAI function-calling schemas for Senpai's sales tools.

Same shape as demo/tools.py's TOOLS. These are the capabilities the junior
assistant (exp3) can call; every one is backed by the deterministic store /
scoring engine in senpai.tools.impl.
"""
from __future__ import annotations

TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "query_spr",
            "description": "Look up deals and recent notes from the sales pipeline (SPR) "
                           "by customer name/ID or rep ID. Use this to prepare for a visit.",
            "parameters": {
                "type": "object",
                "properties": {
                    "customer": {"type": "string", "description": "Customer name or ID (e.g. 'アクメ商事' or 'C01')"},
                    "rep_id": {"type": "string", "description": "Rep ID, e.g. 'R05'"},
                    "deal_id": {"type": "string", "description": "Specific deal ID, e.g. 'D012'"},
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "find_similar_deals",
            "description": "Find comparable past deals for a new or thin customer, matched on "
                           "industry, size and profile tags. Useful when the customer has little history.",
            "parameters": {
                "type": "object",
                "properties": {
                    "customer": {"type": "string", "description": "Customer name or ID"},
                    "industry": {"type": "string", "description": "Industry (e.g. '製造', '医療')"},
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "retrieve_playbook",
            "description": "Retrieve senior reps' tactical advice for a situation, by keywords or "
                           "tags (e.g. '決定先延ばし', '値引き'). Returns attributed snippets.",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "The situation in natural language"},
                    "tags": {"type": "array", "items": {"type": "string"},
                             "description": "Optional situation tags to match"},
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "lookup_customer_environment",
            "description": "Get the customer's IT environment record (PCs, OS, network) — the "
                           "handoff information a rep needs before a technical visit.",
            "parameters": {
                "type": "object",
                "properties": {
                    "customer": {"type": "string", "description": "Customer name or ID"},
                },
                "required": ["customer"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_product_info",
            "description": "Get specs, price and a manual excerpt for a product by SKU or name.",
            "parameters": {
                "type": "object",
                "properties": {
                    "product": {"type": "string", "description": "Product SKU (e.g. 'MFP30') or name"},
                },
                "required": ["product"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "score_deal_health",
            "description": "Assess a deal's health: returns a red/yellow/green band, a risk score "
                           "and the concrete reasons behind it. Use to judge if a deal is really on track.",
            "parameters": {
                "type": "object",
                "properties": {
                    "deal_id": {"type": "string", "description": "Deal ID, e.g. 'D012'"},
                },
                "required": ["deal_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "review_sales_note",
            "description": "Coach a junior on a raw meeting note or daily report. Returns what an "
                           "experienced rep would notice, missing info, risk signals, questions to ask "
                           "next, several possible next moves, and decision factors — it teaches "
                           "reasoning and never gives a single 'correct answer'. Pass the note text; "
                           "add deal_id to fold in that deal's structured signals.",
            "parameters": {
                "type": "object",
                "properties": {
                    "note": {"type": "string", "description": "The meeting note / daily report text to review"},
                    "deal_id": {"type": "string", "description": "Optional related deal ID, e.g. 'D012'"},
                },
                "required": ["note"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "draft_daily_report",
            "description": "Draft an SPR-ready daily sales report (日報) in Japanese from a short "
                           "activity description and optional deal ID.",
            "parameters": {
                "type": "object",
                "properties": {
                    "activity": {"type": "string", "description": "What happened today, in natural language"},
                    "deal_id": {"type": "string", "description": "Related deal ID, if any"},
                },
                "required": ["activity"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "route_to_expert",
            "description": "Find the right senior/expert rep to escalate a question to, matched on "
                           "their specialty tags, and draft a short intro message.",
            "parameters": {
                "type": "object",
                "properties": {
                    "question": {"type": "string", "description": "The question to escalate"},
                    "tags": {"type": "array", "items": {"type": "string"},
                             "description": "Topic tags (e.g. 'ネットワーク', 'サーバー')"},
                },
                "required": ["question"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "summarize_reports",
            "description": "Summarize a rep's recent reports and surface report-reliability flags "
                           "(stale/optimistic/missing-field deals). Manager-facing.",
            "parameters": {
                "type": "object",
                "properties": {
                    "rep_id": {"type": "string", "description": "Rep ID, e.g. 'R05'"},
                },
                "required": ["rep_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_seasonal_context",
            "description": "Get Japanese fiscal-year budget-timing context (the year ends in March) "
                           "to advise on close-timing and budget conversations.",
            "parameters": {
                "type": "object",
                "properties": {
                    "month": {"type": "integer", "description": "Month number 1-12 (default: current)"},
                },
                "required": [],
            },
        },
    },
    # --- Manager + shared tools ---------------------------------------------
    {
        "type": "function",
        "function": {
            "name": "list_at_risk_deals",
            "description": "List at-risk open deals across the whole team (or one rep), worst first. "
                           "Each line shows the owner, customer, risk score and the top reason. "
                           "Defaults to red deals; pass band='yellow' to include yellow too.",
            "parameters": {
                "type": "object",
                "properties": {
                    "rep_id": {"type": "string", "description": "Optional rep ID to limit to one rep, e.g. 'R05'"},
                    "band": {"type": "string", "description": "'red' (default), 'yellow' (red+yellow), or 'green'"},
                    "limit": {"type": "integer", "description": "Max deals to return (default 10)"},
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "team_pipeline_overview",
            "description": "Team pipeline at a glance: open-deal count, total ¥ value, breakdown by "
                           "stage, red/yellow/green health split, and number of flagged reports.",
            "parameters": {
                "type": "object",
                "properties": {
                    "rep_id": {"type": "string", "description": "Optional rep ID to scope to one rep"},
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "team_report_digest",
            "description": "Digest every rep's open deals into one manager view: the flagged/stale/"
                           "optimistic deals grouped by rep, worst first. Use to review the whole team at once.",
            "parameters": {"type": "object", "properties": {}, "required": []},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "rep_coaching_focus",
            "description": "Per-rep rollup (deal count, at-risk count, flagged count, average risk), sorted "
                           "so the reps who need coaching attention come first.",
            "parameters": {"type": "object", "properties": {}, "required": []},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "draft_message",
            "description": "Draft a short, editable Japanese message (a nudge to a rep or a client "
                           "follow-up). Pulls deal context when a deal_id is given. Never sends — the human edits and sends.",
            "parameters": {
                "type": "object",
                "properties": {
                    "to": {"type": "string", "description": "Recipient name, e.g. '伊藤さん' or a client"},
                    "about": {"type": "string", "description": "What the message is about"},
                    "deal_id": {"type": "string", "description": "Optional related deal ID for context"},
                    "purpose": {"type": "string", "description": "Optional purpose, e.g. '進捗確認'"},
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "web_search",
            "description": "Search the web for external information (industry trends, company/customer news, "
                           "competitor info). Use for facts not in the internal data.",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "The search query"},
                },
                "required": ["query"],
            },
        },
    },
]


# --- Role-scoped tool subsets ----------------------------------------------
# Each front end passes its own list to stream_turn(). Built by name from TOOLS
# so a schema is defined exactly once.
_BY_NAME = {t["function"]["name"]: t for t in TOOLS}


def _pick(*names: str) -> list[dict]:
    return [_BY_NAME[n] for n in names]


# Junior assistant: the in-context coaching tools + web_search.
# (review_sales_note is intentionally excluded — it bridges to the friend-owned
#  coach experiment and is kept out of our chat surface for isolation.)
JUNIOR_TOOLS = _pick(
    "query_spr", "find_similar_deals", "retrieve_playbook",
    "lookup_customer_environment", "get_product_info", "score_deal_health",
    "draft_daily_report", "route_to_expert",
    "get_seasonal_context", "web_search",
)

# Manager: team analytics + drill-down + drafting + web_search.
MANAGER_TOOLS = _pick(
    "query_spr", "score_deal_health", "list_at_risk_deals",
    "team_pipeline_overview", "team_report_digest", "rep_coaching_focus",
    "draft_message", "web_search",
)

# Research assistant ("tell me about this customer"): read-only lookups, internal
# first, with web_search to fill external gaps. No drafting/coaching tools — this
# is a grounded research surface, not a generic chat. Order mirrors the intended
# source priority (internal records → deal signals → web).
RESEARCH_TOOLS = _pick(
    "query_spr", "find_similar_deals", "score_deal_health",
    "lookup_customer_environment", "get_product_info",
    "get_seasonal_context", "web_search",
)
