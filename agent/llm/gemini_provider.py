from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any

import requests

from agent.llm.provider import LLMError, LLMProvider, LLMResponse


@dataclass(frozen=True)
class GeminiProvider(LLMProvider):
    api_key: str
    model: str = "gemini-1.5-flash"
    timeout_s: int = 60

    def _url(self) -> str:
        return (
            "https://generativelanguage.googleapis.com/v1beta/models/"
            f"{self.model}:generateContent?key={self.api_key}"
        )

    def generate_text(self, prompt: str) -> LLMResponse:
        payload: dict[str, Any] = {
            "contents": [{"role": "user", "parts": [{"text": prompt}]}],
            "generationConfig": {
                "temperature": 0.2,
                "maxOutputTokens": 4096,
            },
        }
        resp = requests.post(self._url(), json=payload, timeout=self.timeout_s)
        if resp.status_code >= 400:
            raise LLMError(f"Gemini API error {resp.status_code}: {resp.text[:500]}")
        data = resp.json()
        text = ""
        try:
            candidates = data.get("candidates", []) or []
            if candidates:
                parts = candidates[0].get("content", {}).get("parts", []) or []
                if parts:
                    text = parts[0].get("text", "") or ""
        except Exception as e:  # noqa: BLE001
            raise LLMError(f"Failed to parse Gemini response: {e}") from e
        if not text.strip():
            raise LLMError("Gemini returned empty text")
        return LLMResponse(text=text, raw=data)


def from_env() -> GeminiProvider:
    api_key = os.environ.get("LLM_API_KEY", "").strip()
    if not api_key:
        raise LLMError("Missing LLM_API_KEY")
    model = os.environ.get("GEMINI_MODEL", "gemini-1.5-flash").strip() or "gemini-1.5-flash"
    return GeminiProvider(api_key=api_key, model=model)

