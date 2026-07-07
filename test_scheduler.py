import json
from senpai.orchestration.scheduler import AdaptiveScheduler, ToolCall
from senpai.orchestration.metadata import TOOL_METADATA, OperationKind

print("search_notes in metadata:", "search_notes" in TOOL_METADATA)
meta = TOOL_METADATA.get("search_notes")
is_unsafe = not meta or not meta.parallel_safe or meta.kind in (OperationKind.WRITE, OperationKind.EXTERNAL)
print("meta:", meta)
print("is_unsafe:", is_unsafe)

scheduler = AdaptiveScheduler()
calls = [
    ToolCall("call_1", "search_notes", json.dumps({"query": "budget slashed", "customer": "A"})),
    ToolCall("call_2", "search_notes", json.dumps({"query": "budget slashed", "customer": "B"}))
]
plan = scheduler.schedule(calls)
for t in plan.tasks:
    print(t.id, t.depends_on)
