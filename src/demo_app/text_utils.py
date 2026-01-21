from __future__ import annotations

import re

_WS_RE = re.compile(r"\s+")
_NON_ALNUM_RE = re.compile(r"[^a-z0-9-]+")


def normalize_whitespace(text: str) -> str:
    """Collapse all whitespace runs to single spaces and strip ends."""
    # BUG (seed/issue-3): forgot to strip ends.
    return _WS_RE.sub(" ", text)


def slugify_title(title: str, max_len: int = 30) -> str:
    """Lowercase, alnum + hyphens only, collapse runs, and truncate."""
    s = normalize_whitespace(title).lower()
    s = s.replace("_", "-")
    s = re.sub(r"\s+", "-", s)
    s = _NON_ALNUM_RE.sub("", s)
    s = re.sub(r"-{2,}", "-", s).strip("-")
    return s[:max_len].strip("-") or "issue"

