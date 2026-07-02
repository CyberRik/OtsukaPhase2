"""Session focus — the entity the conversation has actually resolved.

**Derived, not mutated.** Read from the conversation the chat loop publishes
(``senpai.tools.conversation``), so it works ACROSS turns even though the server is
stateless per request and a per-turn ``ContextVar`` set on a worker thread does not
survive the thread hop. A live-mutated "focus" object set when a CRM lookup resolved
a customer in one turn would simply be gone by the next turn's document tool.

**Keyed off IDs, not names.** The signal is the unambiguous ids that real tool
results emitted — ``D001`` (deal) / ``C14`` (customer). An id in a tool result means
a tool genuinely resolved that entity, which is authoritative. It deliberately does
NOT re-run fuzzy name matching over free text — that is exactly what produced the
wrong-company deck (a 村田 request pulling an unrelated 松田 record). So grounding can
trust focus and read it BEFORE any last-resort fuzzy prompt match.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

from senpai.data import store
from senpai.tools import conversation as _conv

# Ids as the store emits them: customers C01.., deals D001.. (see data/store).
_DEAL_ID_RE = re.compile(r"\bD\d{3,}\b")
_CUST_ID_RE = re.compile(r"\bC\d{2,}\b")
_YEN_RE = re.compile(r"¥[\d,]+")


@dataclass(frozen=True)
class SessionFocus:
    """The most-specific entity resolved so far this session (any field may be None)."""
    deal_id: str | None = None
    customer_id: str | None = None
    last_quote: str | None = None

    @property
    def customer_name(self) -> str | None:
        return store.customer_name(self.customer_id) if self.customer_id else None

    def __bool__(self) -> bool:
        return bool(self.deal_id or self.customer_id or self.last_quote)


_EMPTY = SessionFocus()


def session_focus() -> SessionFocus:
    """The entity the published conversation has resolved, newest-first: the first
    valid deal id wins (most specific — it also carries its customer); a standalone
    customer id is the fallback; the most recent ¥ figure is the last quote. Empty
    when nothing has been resolved yet (no ids in any tool result)."""
    convo = _conv.conversation()
    if not convo:
        return _EMPTY
    deal_id = deal_customer = standalone_customer = last_quote = None
    for m in reversed(convo):
        # Only real tool results / assistant answers carry resolved ids — a user's
        # free-text request does not (matching that is the fuzzy trap we avoid).
        if m.get("role") not in ("tool", "assistant"):
            continue
        content = m.get("content")
        if not isinstance(content, str) or not content.strip():
            continue
        if last_quote is None:
            mq = _YEN_RE.search(content)
            if mq:
                last_quote = mq.group(0)
        if deal_id is None:
            for cand in _DEAL_ID_RE.findall(content):
                d = store.get_deal(cand)
                if d:
                    deal_id, deal_customer = cand, d.get("customer_id")
                    break
        if standalone_customer is None:
            for cand in _CUST_ID_RE.findall(content):
                if store.get_customer(cand):
                    standalone_customer = cand
                    break
        if deal_id and last_quote and standalone_customer:
            break
    customer_id = deal_customer or standalone_customer
    if not (deal_id or customer_id or last_quote):
        return _EMPTY
    return SessionFocus(deal_id=deal_id, customer_id=customer_id, last_quote=last_quote)
