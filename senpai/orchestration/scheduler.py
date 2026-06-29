import json
from dataclasses import dataclass

from senpai.orchestration.capability import Task, ExecutionPlan, TaskPolicy
from senpai.orchestration.metadata import TOOL_METADATA, OperationKind

@dataclass
class ToolCall:
    id: str
    name: str
    arguments: str  # JSON string
    
    def parsed_args(self) -> dict:
        try:
            return json.loads(self.arguments)
        except Exception:
            return {}

class AdaptiveScheduler:
    """
    Sits between the ReAct loop and the ExecutionEngine.
    Inspects emitted tool calls, checks CapabilityMetadata, removes duplicates,
    and dynamically builds a deterministic ExecutionPlan (DAG).
    """
    
    def schedule(self, calls: list[ToolCall]) -> ExecutionPlan:
        tasks: list[Task] = []
        seen_signatures: set[str] = set()
        
        # Track dependencies to enforce serialization barriers for unsafe/WRITE tasks.
        current_barrier_deps: frozenset[str] = frozenset()

        for call in calls:
            # 1. Duplicate elimination
            sig = f"{call.name}:{call.arguments}"
            if sig in seen_signatures:
                continue
            seen_signatures.add(sig)

            # 2. Metadata Inspection
            meta = TOOL_METADATA.get(call.name)
            is_unsafe = not meta or not meta.parallel_safe or meta.kind in (OperationKind.WRITE, OperationKind.EXTERNAL)
            
            # Map retries and timeout from metadata to policy
            policy = TaskPolicy(
                timeout_s=meta.timeout if meta else 30.0,
                retries=meta.retries if (meta and meta.idempotent) else 0
            )

            # 3. Dependency DAG construction
            if is_unsafe:
                # Serialization barrier: this unsafe task must wait for ALL prior tasks to finish.
                deps = frozenset(t.id for t in tasks)
                task = Task(
                    id=call.id,
                    capability="tool",
                    op=call.name,
                    inputs=call.parsed_args(),
                    depends_on=deps,
                    policy=policy,
                    summary=f"Running {call.name}"
                )
                tasks.append(task)
                # Subsequent tasks must wait for THIS unsafe task to finish.
                current_barrier_deps = frozenset([task.id])
            else:
                # Parallel-safe task: only depends on the most recent barrier (if any).
                task = Task(
                    id=call.id,
                    capability="tool",
                    op=call.name,
                    inputs=call.parsed_args(),
                    depends_on=current_barrier_deps,
                    policy=policy,
                    summary=f"Running {call.name}"
                )
                tasks.append(task)
                
        plan = ExecutionPlan(tuple(tasks))
        plan.validate()
        return plan
