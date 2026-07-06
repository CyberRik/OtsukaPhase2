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
            "name": "find_deals",
            "description": "Grounded faceted search over real past/current deals. Filters by any "
                           "combination of: product_category, customer industry, customer size, "
                           "outcome (won/lost/open), order_rank, amount band, or a product code — "
                           "and reports the win/lost/open breakdown of the matches. Use this to "
                           "answer 'show me past <category> deals at <size>/<industry> companies "
                           "and how they went' BEFORE giving advice, so the answer is from data. "
                           "Filter values must be real values present in the data; if a filter "
                           "matches nothing, the tool lists the valid values to use.",
            "parameters": {
                "type": "object",
                "properties": {
                    "product_category": {"type": "string", "description": "Deal product category, e.g. 'サーバー', 'ソフトウェア', 'ネットワーク機器' (substring ok)"},
                    "industry": {"type": "string", "description": "Customer industry, e.g. '製造', '医療' (substring ok)"},
                    "size": {"type": "string", "description": "Customer size band, e.g. '中規模', '小規模'"},
                    "outcome": {"type": "string", "description": "'won', 'lost', or 'open' (derived from order_rank)"},
                    "order_rank": {"type": "string", "description": "Exact/substring order_rank, e.g. '3_A'"},
                    "min_amount": {"type": "number", "description": "Minimum total_order_amount (¥)"},
                    "max_amount": {"type": "number", "description": "Maximum total_order_amount (¥)"},
                    "product_code": {"type": "string", "description": "A specific product code the deal includes, e.g. 'MON27'"},
                    "limit": {"type": "integer", "description": "Max deals to list (default 10)"},
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
            "name": "search_notes",
            "description": "Semantic search across CRM daily reports (日報) ONLY — not the "
                           "user's local files. Finds notes that mean the same thing as the "
                           "query even when worded differently (e.g. '予算が理由で停滞' also "
                           "surfaces 'コスト面で渋い'). ALWAYS pass `customer` (the account in "
                           "focus) for any account-specific question — this restricts the "
                           "search to that customer's own notes. Omit `customer` ONLY for "
                           "deliberate cross-account research; results then span all customers "
                           "and are labelled as such. If this comes back thin/generic, or the "
                           "user's phrasing could mean an actual document (e.g. names a file, "
                           "says 'the notes', 'the doc', or asks to add/edit/apply something "
                           "INTO them), also call search_workspace_documents — the real notes "
                           "may live in a local file, not a daily report.",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "What to look for, in natural language"},
                    "customer": {"type": "string", "description": "The account in focus (name or ID). "
                                 "Scopes the search to this customer's notes. Pass it whenever the "
                                 "question is about a specific account."},
                    "limit": {"type": "integer", "description": "Max notes to return (default 5)"},
                },
                "required": ["query"],
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
            "name": "morning_briefing",
            "description": "The rep's prioritized to-do for today: their open deals ranked by "
                           "urgency × value, each with ONE concrete next action (e.g. follow up, "
                           "identify the decision-maker, re-confirm the close date). Includes a "
                           "predictive nudge for deals about to breach their contact cadence. "
                           "Omit rep_id for a whole-team view. Use this to answer 'what should I "
                           "do today?' / '今日やるべきことは?'.",
            "parameters": {
                "type": "object",
                "properties": {
                    "rep_id": {"type": "string", "description": "Rep ID to brief, e.g. 'R12'. Omit for the whole team."},
                    "limit": {"type": "integer", "description": "Max actions to return (default 10)"},
                },
                "required": [],
            },
        },
    },
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
    {
        "type": "function",
        "function": {
            "name": "web_research",
            "description": "Research the open web by ACTUALLY VISITING pages (a real crawler), then "
                           "answer grounded in what was on them. Auto-routes on the input: (a) a "
                           "website URL or bare domain → crawls that site and returns a pre-call "
                           "intel brief (company overview, products, recent news, IR/財務 docs, "
                           "talking points); (b) a question with no URL (e.g. '築地の営業会社トップ5') "
                           "→ web-searches it, crawls the top result sites, and answers with source "
                           "URLs. Every claim carries a source link. Prefer this over web_search "
                           "when the user pastes a URL or wants real page content, not just snippets.",
            "parameters": {
                "type": "object",
                "properties": {
                    "input": {"type": "string",
                              "description": "A website URL (e.g. 'https://www.example.co.jp') OR a "
                                             "research question (e.g. '築地の営業支援会社を教えて')"},
                    "max_pages": {"type": "integer",
                                  "description": "Max pages per site to visit (default 6, capped at 12)"},
                    "max_sites": {"type": "integer",
                                  "description": "For a question: how many distinct sites to crawl (default 3, max 5)"},
                },
                "required": ["input"],
            },
        },
    },
    # --- Knowledge RAG + sales-action tools (ported from demo/tools.py) -------
    {
        "type": "function",
        "function": {
            "name": "search_knowledge",
            "description": "Search the validated internal knowledge corpus — senior-rep "
                           "principles, approved coaching cases and the playbook — for advice "
                           "grounded in real interviews. Returns short attributed/cited snippets. "
                           "Prefer this over web_search for 'how should I handle…' questions.",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "The situation in natural language"},
                    "tags": {"type": "array", "items": {"type": "string"},
                             "description": "Optional situation tags (e.g. '値引き', '決定先延ばし')"},
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "search_solutions",
            "description": "Search Otsuka Shokai's real product/solution pages for what to offer "
                           "a customer — named products/services with a short description, each "
                           "cited by source URL. Use this for 'what should we propose/recommend' "
                           "questions; prefer search_products instead when the rep needs a SKU "
                           "price lookup, not a solution pitch.",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string",
                              "description": "The customer's need/problem or product category, in natural language"},
                    "category": {"type": "string",
                                 "description": "Optional: restrict to a URL-derived category substring (e.g. 'security', 'cad')"},
                },
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "search_products",
            "description": "Search the Otsuka product catalog by category, price range, or keyword. "
                           "Returns matching products with code, name and unit price (JPY).",
            "parameters": {
                "type": "object",
                "properties": {
                    "category": {"type": "string",
                                 "description": "Category term to match (e.g. '複合機', 'サーバー', 'PC')"},
                    "max_price": {"type": "number", "description": "Maximum unit price in JPY"},
                    "min_price": {"type": "number", "description": "Minimum unit price in JPY"},
                    "keyword": {"type": "string", "description": "Free-text term to match in name/specs"},
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "create_quote",
            "description": "Build a price quote (estimate) for one or more catalog products: line "
                           "totals, optional discount, tax and grand total. A draft — never sent.",
            "parameters": {
                "type": "object",
                "properties": {
                    "items": {
                        "type": "array",
                        "description": "Products to quote.",
                        "items": {
                            "type": "object",
                            "properties": {
                                "sku": {"type": "string", "description": "Product code or name"},
                                "qty": {"type": "integer", "description": "Quantity"},
                            },
                            "required": ["sku", "qty"],
                        },
                    },
                    "discount_pct": {"type": "number", "description": "Discount percent on the subtotal (0-100)"},
                    "customer": {"type": "string", "description": "Customer/company name for the header"},
                    "tax_pct": {"type": "number", "description": "Sales-tax percent (default 10)"},
                },
                "required": ["items"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "schedule_meeting",
            "description": "Book a meeting on the calendar in two steps so the rep stays in the "
                           "loop. First call with confirm=false (default) to return a draft for the "
                           "rep to review; only after the rep explicitly says to book it, call again "
                           "with confirm=true to create a real Google Calendar event. Resolve "
                           "relative dates to YYYY-MM-DD first.",
            "parameters": {
                "type": "object",
                "properties": {
                    "title": {"type": "string", "description": "Meeting title"},
                    "date": {"type": "string", "description": "Date as YYYY-MM-DD"},
                    "start_time": {"type": "string", "description": "Start time as 24h HH:MM (JST)"},
                    "duration_hours": {"type": "number", "description": "Length in hours (default 1)"},
                    "attendees": {"type": "array", "items": {"type": "string"},
                                  "description": "Attendee names or emails"},
                    "description": {"type": "string", "description": "Optional agenda/notes"},
                    "confirm": {"type": "boolean",
                                "description": "Set true ONLY when the rep has explicitly confirmed; "
                                               "actually books the event. Default false returns a draft."},
                },
                "required": ["title", "date", "start_time"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "send_email",
            "description": "Prepare an email draft to a recipient. Never actually sends — the human "
                           "edits and sends. Use for follow-ups / quote delivery messages.",
            "parameters": {
                "type": "object",
                "properties": {
                    "to": {"type": "string", "description": "Recipient name or email address"},
                    "subject": {"type": "string"},
                    "body": {"type": "string"},
                },
                "required": ["to", "subject", "body"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_calendar",
            "description": "Get the schedule for a given day (YYYY-MM-DD or 'today'). Simulated demo data.",
            "parameters": {
                "type": "object",
                "properties": {
                    "day": {"type": "string", "description": "Date as YYYY-MM-DD or 'today'"},
                },
                "required": ["day"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "query_graph",
            "description": "Answer relational, multi-hop questions over the sales knowledge graph "
                           "(customer→deal→activity→rep→product) that simple lookups can't. Intents: "
                           "'reps_who_win' (who has the best win-rate on deals filtered by category / "
                           "industry / activity type — e.g. 'reps who win サーバー deals in 製造業 after "
                           "a site survey'); 'account' (one customer's whole deal/rep/product network); "
                           "'connections' (how two entities are linked); 'similar' (deals related to a "
                           "deal_id by shared rep/product/industry).",
            "parameters": {
                "type": "object",
                "properties": {
                    "intent": {"type": "string",
                               "description": "'reps_who_win' | 'account' | 'connections' | 'similar'"},
                    "category": {"type": "string", "description": "Product category filter, e.g. 'サーバー'"},
                    "industry": {"type": "string", "description": "Customer industry filter, e.g. '製造'"},
                    "after_activity_type": {"type": "string",
                                            "description": "Require deals that had this activity type, e.g. '001_Scheduled'"},
                    "customer": {"type": "string", "description": "Customer name/ID (intent='account')"},
                    "deal_id": {"type": "string", "description": "Deal ID (intent='similar'), e.g. 'D012'"},
                    "entity_a": {"type": "string", "description": "First entity (intent='connections')"},
                    "entity_b": {"type": "string", "description": "Second entity (intent='connections')"},
                    "limit": {"type": "integer", "description": "Max rows (default 8)"},
                },
                "required": ["intent"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "segment_intelligence",
            "description": "Answer AGGREGATE / thematic / portfolio questions across market "
                           "segments (product category × customer industry) that per-deal or "
                           "per-account lookups can't: win rates, the common FAILURE MODES "
                           "behind lost deals, and the recommended play per segment. Use for "
                           "questions like 'なぜ製造業のサーバー案件は負ける？', 'common failure "
                           "modes across our lost deals', 'which segment loses most and why', "
                           "'どのカテゴリの勝率が低い？'. Each segment answer is grounded in real "
                           "tallies from the deal-health engine and cites the evidence deal ids. "
                           "Pass category and/or industry to focus; omit both for a portfolio "
                           "overview.",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string",
                              "description": "The manager's thematic question (used to pick relevant segments)"},
                    "category": {"type": "string", "description": "Product category filter, e.g. 'サーバー'"},
                    "industry": {"type": "string", "description": "Customer industry filter, e.g. '製造業'"},
                    "outcome": {"type": "string", "description": "'won' | 'lost' | 'all' (default 'all') — nudges ranking"},
                    "limit": {"type": "integer", "description": "Max segments to return (default 6)"},
                },
                "required": ["query"],
            },
        },
    },
    # --- Document generation: the chatbot's "do stuff" tools ------------------
    {
        "type": "function",
        "function": {
            "name": "generate_proposal",
            "description": "Generate a persuasive PowerPoint (.pptx) SALES PROPOSAL for a "
                           "specific deal, grounded in its SPR data. It follows a full "
                           "proposal arc (background → challenges → solution → ROI → next "
                           "steps), mapping the customer's real pain points against the "
                           "deal's real financials, quote, and same-category comparable "
                           "deals — persuasive framing, grounded numbers. Builds the file "
                           "directly in one call (no confirmation step). Use when the rep "
                           "asks to make a proposal/提案書 deck for a deal.",
            "parameters": {
                "type": "object",
                "properties": {
                    "deal_id": {"type": "string", "description": "The deal to build the proposal for, e.g. 'D012'"},
                    "lang": {"type": "string", "description": "'ja' (default) or 'en'"},
                    "confirm": {"type": "boolean",
                                "description": "Set true ONLY after the rep confirms; actually creates the file. Default false returns a preview, after which you MUST stop and ask the user for confirmation."},
                },
                "required": ["deal_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "generate_ringisho",
            "description": "Generate a formal Japanese internal-approval document (稟議書) as "
                           "a Word file (.docx) for a specific deal, written from the "
                           "customer's IT-manager persona pitching their own CEO, using the "
                           "deal's real financials to justify solving the SPR-logged pain "
                           "points. Two-step: confirm=false (default) returns a preview; "
                           "confirm=true builds and saves the file. Use when the rep asks "
                           "for a 稟議書 / approval document.",
            "parameters": {
                "type": "object",
                "properties": {
                    "deal_id": {"type": "string", "description": "The deal to build the 稟議書 for, e.g. 'D012'"},
                    "confirm": {"type": "boolean",
                                "description": "Set true ONLY after the rep confirms; actually creates the file. Default false returns a preview, after which you MUST stop and ask the user for confirmation."},
                },
                "required": ["deal_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "generate_pptx",
            "description": "Generate a general-purpose PowerPoint (.pptx) on ANY topic from a "
                           "natural-language prompt — not tied to a deal. The deck is authored "
                           "by the model and can be about anything (e.g. 'make a deck about "
                           "GTA 6'); no fixed slide count. Grounding is automatic: external/"
                           "factual topics (products, prices, 'best-of', comparisons, current "
                           "models) are web-grounded by default, and a customer grounds it in "
                           "internal records — you normally do NOT set use_web. Builds the file "
                           "directly in one call (no confirmation step). Use generate_proposal "
                           "instead for a deal-specific sales proposal.",
            "parameters": {
                "type": "object",
                "properties": {
                    "prompt": {"type": "string", "description": "What the presentation should be about"},
                    "title": {"type": "string", "description": "Optional title override"},
                    "use_web": {"type": "boolean", "description": "Override web grounding. Omit to auto-decide (external/factual topics are web-grounded automatically). Set false to force the model's own knowledge; true to force a web search."},
                    "customer": {"type": "string", "description": "Optional customer name/ID to ground the deck in internal records"},
                    "lang": {"type": "string", "description": "'ja' (default) or 'en'"},
                    "confirm": {"type": "boolean",
                                "description": "Set true ONLY after the rep confirms; actually creates the file. Default false returns a preview, after which you MUST stop and ask the user for confirmation."},
                },
                "required": ["prompt"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "generate_docx",
            "description": "Generate a general-purpose Word document (.docx) on ANY topic from "
                           "a natural-language prompt — not tied to a deal. Authored by the "
                           "model; can be about anything. Grounding is automatic: external/"
                           "factual topics are web-grounded by default, and a customer grounds "
                           "it in internal records — you normally do NOT set use_web. Builds the "
                           "file directly in one call (no confirmation step). Use "
                           "generate_ringisho instead for a deal-specific 稟議書.",
            "parameters": {
                "type": "object",
                "properties": {
                    "prompt": {"type": "string", "description": "What the document should be about"},
                    "title": {"type": "string", "description": "Optional title override"},
                    "use_web": {"type": "boolean", "description": "Override web grounding. Omit to auto-decide (external/factual topics are web-grounded automatically). Set false to force the model's own knowledge; true to force a web search."},
                    "customer": {"type": "string", "description": "Optional customer name/ID to ground the document in internal records"},
                    "lang": {"type": "string", "description": "'ja' (default) or 'en'"},
                    "confirm": {"type": "boolean",
                                "description": "Set true ONLY after the rep confirms; actually creates the file. Default false returns a preview, after which you MUST stop and ask the user for confirmation."},
                },
                "required": ["prompt"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "search_workspace_documents",
            "description": "Find and READ relevant local documents (PDF, DOCX, PPTX, "
                           "XLSX, TXT, Markdown) from the user's sandboxed workspace "
                           "folder, and return their text with per-file citations. Use "
                           "when the answer may live in the user's own files (a proposal "
                           "deck, meeting notes, a spreadsheet, a PDF) rather than the CRM "
                           "or the web — e.g. 'what did we send Endo Kogyo?', 'summarize my "
                           "notes on this account'. Read-only; never edits or deletes.",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string",
                              "description": "What to look for; matched against file names/paths. Empty returns the most recent documents."},
                    "limit": {"type": "integer",
                              "description": "Max documents to read (default/cap set by the server)."},
                },
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "edit_workspace_document",
            "description": "Create or modify a local text document (e.g. .txt, .md, .csv, .json) in the user's workspace. "
                           "This is the ONLY way to actually persist something into a local file — if the user asks to "
                           "add/append/apply/update/edit/save/反映/追加/適用/編集 information INTO a file or notes you "
                           "already found (e.g. via search_workspace_documents), you MUST call this tool with the full "
                           "merged content, not just describe the merge in your chat answer — never claim something was "
                           "saved or applied unless this tool actually ran. "
                           "You must pass confirm=False first to return a preview. Then ask the user to confirm. "
                           "If they confirm, run again with confirm=True to commit the write to disk.",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "The absolute path or relative path from the workspace to save the file."},
                    "content": {"type": "string", "description": "The text content to write into the file."},
                    "confirm": {"type": "boolean", "description": "Set true ONLY after the user confirms; actually writes the file. Default false returns a preview."},
                },
                "required": ["path", "content"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "move_workspace_document",
            "description": "Move or rename a local document in the user's workspace. "
                           "You must pass confirm=False first to return a preview. Then ask the user to confirm. "
                           "If they confirm, run again with confirm=True to commit the move. "
                           "Can be used to organize all types of files, including PDFs and PPTXs.",
            "parameters": {
                "type": "object",
                "properties": {
                    "src": {"type": "string", "description": "The current path of the file."},
                    "dst": {"type": "string", "description": "The new path for the file."},
                    "confirm": {"type": "boolean", "description": "Set true ONLY after the user confirms; actually moves the file. Default false returns a preview."},
                },
                "required": ["src", "dst"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "advise_solutions",
            "description": "Recommend appropriate Otsuka solutions for a customer based on their context (expansion signals, environment gaps, and category). Use this when asked 'what should I propose?' or to generate a list of targeted solution recommendations.",
            "parameters": {
                "type": "object",
                "properties": {
                    "customer": {"type": "string", "description": "Customer name or ID to get recommendations for"},
                    "deal_id": {"type": "string", "description": "Optional specific deal ID to focus recommendations around"},
                },
                "required": ["customer"],
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
    "query_spr", "find_deals", "find_similar_deals", "retrieve_playbook", "search_knowledge",
    "search_solutions",
    "search_notes", "lookup_customer_environment", "get_product_info", "search_products",
    "create_quote", "score_deal_health", "draft_daily_report", "schedule_meeting",
    "send_email", "get_calendar", "route_to_expert", "morning_briefing",
    "get_seasonal_context", "web_search", "web_research", "search_workspace_documents", "edit_workspace_document", "move_workspace_document",
    "generate_proposal", "generate_ringisho", "generate_pptx", "generate_docx", "advise_solutions",
)

# Manager: team analytics + drill-down + drafting + semantic/graph search + web.
MANAGER_TOOLS = _pick(
    "query_spr", "find_deals", "score_deal_health", "morning_briefing", "list_at_risk_deals",
    "team_pipeline_overview", "team_report_digest", "rep_coaching_focus",
    "search_knowledge", "search_solutions", "search_notes", "query_graph", "segment_intelligence", "search_products",
    "create_quote", "schedule_meeting",
    "send_email", "get_calendar", "draft_message", "web_search", "web_research", "search_workspace_documents", "edit_workspace_document", "move_workspace_document",
    "generate_proposal", "generate_ringisho", "generate_pptx", "generate_docx", "advise_solutions",
)

# Research assistant ("tell me about this customer"): read-only lookups, internal
# first, with web_search to fill external gaps. No drafting/coaching tools — this
# is a grounded research surface, not a generic chat. Order mirrors the intended
# source priority (internal records → deal signals → web).
RESEARCH_TOOLS = _pick(
    "query_spr", "find_deals", "find_similar_deals", "score_deal_health", "search_notes",
    "lookup_customer_environment", "get_product_info", "search_solutions", "segment_intelligence",
    "get_seasonal_context", "web_search", "web_research", "search_workspace_documents", "edit_workspace_document", "move_workspace_document",
)
