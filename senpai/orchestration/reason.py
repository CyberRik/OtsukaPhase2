"""Extension seam: the Reasoner interface — the single synthesis over a bundle.

A Reasoner consumes a reasoner-view (from the bundle, optionally reduced) and
streams the final artifact text. It is the ONE place reasoning happens; capabilities
never reason.

M0 ships `EchoReasoner` (deterministic, GPU-free — for tests and the self-check)
and `LLMReasoner`, a thin wrapper over the existing `senpai.llm.client` that M1
wires into the routes. Swapping reasoner implementations changes nothing upstream.
"""
from __future__ import annotations

import json
from typing import Iterator, Protocol


class Reasoner(Protocol):
    def stream(self, view: dict, *, system: str, instruction: str) -> Iterator[str]:
        ...


class EchoReasoner:
    """Deterministic, no-LLM. Emits a compact textual digest of the evidence — used
    by the self-test and any unit test that must not hit a model."""

    def stream(self, view: dict, *, system: str = "", instruction: str = "") -> Iterator[str]:
        frags = view.get("fragments", [])
        yield f"{len(frags)} evidence fragment(s):\n"
        for f in frags:
            cites = ", ".join(f.get("citations", [])) or "-"
            yield f"- [{f.get('capability')}/{f.get('op')}] {json.dumps(f.get('data'), ensure_ascii=False)} (出典: {cites})\n"


class LLMReasoner:
    """Routed synthesis via the existing client. Lazy import so M0 stays import-light
    and GPU-free until a route actually reasons."""

    def __init__(self, *, no_think: bool = True, max_tokens: int = 1200,
                 temperature: float = 0.3) -> None:
        self.no_think = no_think
        self.max_tokens = max_tokens
        self.temperature = temperature

    def stream(self, view: dict, *, system: str, instruction: str) -> Iterator[str]:
        from senpai.llm.client import stream_complete  # lazy
        prompt = (f"{instruction}\n\n"
                  f"Evidence (JSON, structured — use only this):\n"
                  f"{json.dumps(view, ensure_ascii=False, indent=2)}")
        messages = [{"role": "system", "content": system},
                    {"role": "user", "content": prompt}]
        yield from stream_complete(
            messages, temperature=self.temperature, max_tokens=self.max_tokens,
            no_think=self.no_think, allow_fallback=False,
        )
