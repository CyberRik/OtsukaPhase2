import json
from senpai.orchestration.scheduler import AdaptiveScheduler, ToolCall
from senpai.agent.capabilities import build_registry
from senpai.orchestration.engine import ExecutionEngine
import senpai.orchestration.events as events

scheduler = AdaptiveScheduler()
calls = [
    ToolCall("call_1", "search_notes", json.dumps({"query": "budget slashed", "customer": "A"})),
    ToolCall("call_2", "search_notes", json.dumps({"query": "budget slashed", "customer": "B"}))
]
plan = scheduler.schedule(calls)

engine = ExecutionEngine(build_registry())
def on_event(ev):
    print("Event:", ev)

bundle = engine.run(plan, on_event)
print("Bundle fragments:", bundle.fragments)
