import json
from senpai.orchestration.scheduler import AdaptiveScheduler, ToolCall
from senpai.agent.capabilities import build_registry
from senpai.orchestration.engine import ExecutionEngine
from senpai.orchestration.evidence import EvidenceBundle

calls = [
    ("call_1", "search_notes", json.dumps({"query": "budget slashed or 予算削減", "customer": "グローバルテック"})),
    ("call_2", "search_notes", json.dumps({"query": "budget slashed or 予算削減", "customer": "未来工業"}))
]

def _canon_args(arguments) -> str:
    try:
        d = json.loads(arguments) if isinstance(arguments, str) else (arguments or {})
        return json.dumps(d, sort_keys=True, ensure_ascii=False)
    except Exception:
        return str(arguments)

fresh = []
fresh_ids = set()
for cid, name, args in calls:
    fresh.append((cid, name, args))
    fresh_ids.add(cid)

sched_calls = [ToolCall(id=cid, name=name, arguments=args) for cid, name, args in fresh]
scheduler = AdaptiveScheduler()
plan = scheduler.schedule(sched_calls)
engine = ExecutionEngine(build_registry())
def _ignore_events(evt: dict) -> None:
    pass

bundle = engine.run(plan, _ignore_events)

for cid, name, args in calls:
    if cid not in fresh_ids: continue
    ev_frag = bundle.get(cid) if bundle else None
    result = ev_frag.status if ev_frag else "[error] Task skipped"
    print(f"{cid} -> {result}")

