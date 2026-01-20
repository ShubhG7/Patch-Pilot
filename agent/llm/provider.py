from __future__ import annotations

from dataclasses import dataclass


class LLMError(RuntimeError):
    pass


@dataclass(frozen=True)
class LLMResponse:
    text: str
    raw: dict | None = None


class LLMProvider:
    """Minimal provider interface to keep PatchPilot portable."""

    def generate_text(self, prompt: str) -> LLMResponse:  # pragma: no cover - interface
        raise NotImplementedError

