from __future__ import annotations

import re


def slugify(text: str, max_len: int = 30) -> str:
    s = text.strip().lower()
    s = re.sub(r"\s+", "-", s)
    s = re.sub(r"[^a-z0-9-]+", "", s)
    s = re.sub(r"-{2,}", "-", s).strip("-")
    s = s[:max_len].strip("-")
    return s or "issue"

