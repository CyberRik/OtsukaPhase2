from enum import Enum
from dataclasses import dataclass

class OperationKind(Enum):
    READ = "read"         # Safe, deterministic data fetching
    SEARCH = "search"     # Safe, non-deterministic queries (e.g., web_search)
    COMPUTE = "compute"   # CPU-bound data transformation
    WRITE = "write"       # State-mutating internal actions
    EXTERNAL = "external" # State-mutating external actions (e.g., send_email)

@dataclass
class CapabilityMetadata:
    kind: OperationKind
    parallel_safe: bool = True
    idempotent: bool = True
    cacheable: bool = False
    requires_confirmation: bool = False
    max_concurrency: int = 8
    timeout: int = 30
    retries: int = 2

# Global registry of metadata for all tools exposed to the LLM.
# Read/Search tools are generally parallel_safe.
# Write/External tools are strictly serialized and may require confirmation.
TOOL_METADATA: dict[str, CapabilityMetadata] = {
    "query_spr": CapabilityMetadata(OperationKind.READ, cacheable=True),
    "find_deals": CapabilityMetadata(OperationKind.SEARCH, cacheable=True),
    "find_similar_deals": CapabilityMetadata(OperationKind.SEARCH, cacheable=True),
    "retrieve_playbook": CapabilityMetadata(OperationKind.SEARCH, cacheable=True),
    "search_notes": CapabilityMetadata(OperationKind.SEARCH, cacheable=True),
    "lookup_customer_environment": CapabilityMetadata(OperationKind.READ, cacheable=True),
    "get_product_info": CapabilityMetadata(OperationKind.READ, cacheable=True),
    "score_deal_health": CapabilityMetadata(OperationKind.COMPUTE),
    "review_sales_note": CapabilityMetadata(OperationKind.COMPUTE),
    "draft_daily_report": CapabilityMetadata(OperationKind.COMPUTE),
    "route_to_expert": CapabilityMetadata(OperationKind.COMPUTE),
    "summarize_reports": CapabilityMetadata(OperationKind.COMPUTE),
    "get_seasonal_context": CapabilityMetadata(OperationKind.READ, cacheable=True),
    "morning_briefing": CapabilityMetadata(OperationKind.COMPUTE),
    "list_at_risk_deals": CapabilityMetadata(OperationKind.READ),
    "team_pipeline_overview": CapabilityMetadata(OperationKind.COMPUTE),
    "team_report_digest": CapabilityMetadata(OperationKind.COMPUTE),
    "rep_coaching_focus": CapabilityMetadata(OperationKind.COMPUTE),
    "draft_message": CapabilityMetadata(OperationKind.COMPUTE),
    "web_search": CapabilityMetadata(OperationKind.SEARCH, max_concurrency=4, retries=3),
    "search_knowledge": CapabilityMetadata(OperationKind.SEARCH, cacheable=True),
    "search_products": CapabilityMetadata(OperationKind.SEARCH, cacheable=True),
    "create_quote": CapabilityMetadata(OperationKind.COMPUTE),
    "schedule_meeting": CapabilityMetadata(OperationKind.EXTERNAL, parallel_safe=False, idempotent=False, requires_confirmation=True),
    "send_email": CapabilityMetadata(OperationKind.EXTERNAL, parallel_safe=False, idempotent=False, requires_confirmation=True),
    "get_calendar": CapabilityMetadata(OperationKind.READ, cacheable=True),
    "query_graph": CapabilityMetadata(OperationKind.SEARCH, cacheable=True),
    "generate_proposal": CapabilityMetadata(OperationKind.EXTERNAL, parallel_safe=False, idempotent=False, requires_confirmation=True),
    "generate_ringisho": CapabilityMetadata(OperationKind.EXTERNAL, parallel_safe=False, idempotent=False, requires_confirmation=True),
    "generate_pptx": CapabilityMetadata(OperationKind.EXTERNAL, parallel_safe=False, idempotent=False, requires_confirmation=True),
    "generate_docx": CapabilityMetadata(OperationKind.EXTERNAL, parallel_safe=False, idempotent=False, requires_confirmation=True),
}

