"""Explicit outcome markers for tool results.

A tool that finds nothing must SAY so in a way the loop can detect mechanically.
Before this module, `_is_substantive` guessed from prose — it looked for 見つかりません
anywhere, or ありません inside the first 20 characters. That worked by luck of
phrasing: 「…の環境情報は未登録です。」 announced a miss in Japanese but read as evidence
to the loop, and any tool whose miss message happened to word things differently, or
put ありません at character 21, silently became "grounding" the model then answered from.

`[error]` was already a machine-readable prefix in this codebase. `[not_found]` is the
same convention extended to the other kind of non-result: the call succeeded, there was
simply nothing there. Both are misses; neither is evidence.

Tools should return `not_found("<human message>")` rather than a bare string. The marker
is visible to the model and in the UI, which is intentional — the same way `[error]` is.
"""
from __future__ import annotations

ERROR = "[error]"
NOT_FOUND = "[not_found]"

# Prose fallbacks for miss messages produced OUTSIDE senpai/tools/impl.py (workspace,
# crawl, coach context). Kept so the loop keeps recognising them until those callers
# adopt the marker. New code should not rely on these — return not_found() instead.
_LEGACY_MISS_PHRASES = ("見つかりません", "見つかりませんでした")


def not_found(message: str) -> str:
    """Tag a human-readable 'nothing matched' message as a machine-readable miss."""
    return f"{NOT_FOUND} {message}"


def is_error(text: str) -> bool:
    return isinstance(text, str) and text.startswith(ERROR)


def is_not_found(text: str) -> bool:
    return isinstance(text, str) and text.startswith(NOT_FOUND)


def is_miss(text: str) -> bool:
    """True when a tool result carries no usable information — an error, an explicit
    not-found, or a legacy prose miss. The loop must never treat these as grounding."""
    if not isinstance(text, str):
        return True
    if is_error(text) or is_not_found(text):
        return True
    if any(p in text for p in _LEGACY_MISS_PHRASES):
        return True
    # Legacy: 「…はありません」 / 「…がありません」 as a leading clause. Bounded to the
    # opening of the string so a long report that merely *mentions* ありません mid-prose
    # (e.g. an analysis of why a deal is not progressing) is not misread as a miss.
    return "ありません" in text[:20]
