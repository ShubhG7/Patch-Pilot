from __future__ import annotations

from dataclasses import dataclass

from agent.llm.provider import LLMError, LLMProvider, LLMResponse


@dataclass(frozen=True)
class OpenAIProvider(LLMProvider):
    """Compile-ready stub for provider switchability (not used in this demo)."""

    api_key: str
    model: str = "gpt-4.1-mini"

    def generate_text(self, prompt: str) -> LLMResponse:
        raise LLMError("OpenAIProvider is a stub in this demo; use GeminiProvider.")

