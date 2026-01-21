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
    api_version: str = "v1beta"
    timeout_s: int = 60

    def _url(self, *, api_version: str, model: str) -> str:
        # Some deployments expect model names without the "models/" prefix; normalize here.
        m = model.removeprefix("models/").strip()
        return (
            f"https://generativelanguage.googleapis.com/{api_version}/models/"
            f"{m}:generateContent?key={self.api_key}"
        )

    def _post_generate(self, *, api_version: str, model: str, payload: dict[str, Any]) -> requests.Response:
        return requests.post(self._url(api_version=api_version, model=model), json=payload, timeout=self.timeout_s)

    def generate_text(self, prompt: str) -> LLMResponse:
        payload: dict[str, Any] = {
            "contents": [{"role": "user", "parts": [{"text": prompt}]}],
            "generationConfig": {
                "temperature": 0.2,
                "maxOutputTokens": 4096,
            },
        }

        # Robust fallbacks:
        # - API versions: v1beta, then v1 (some orgs/projects are pinned differently)
        # - Model names: try user-provided, then common "latest" variants.
        api_versions = [self.api_version, "v1"] if self.api_version != "v1" else ["v1", "v1beta"]
        candidate_models = [
            self.model,
            f"{self.model}-latest",
            "gemini-2.0-flash",
            "gemini-2.0-flash-lite",
            "gemini-1.5-flash-latest",
        ]
        last_err: str | None = None
        resp: requests.Response | None = None
        for v in api_versions:
            for m in candidate_models:
                resp = self._post_generate(api_version=v, model=m, payload=payload)
                if resp.status_code < 400:
                    break
                last_err = f"{resp.status_code}: {resp.text[:500]}"
                # Only continue fallback on "not found"/unsupported; for auth/quota errors, fail fast.
                if resp.status_code in {401, 403, 429}:
                    raise LLMError(f"Gemini API error {last_err}")
            if resp is not None and resp.status_code < 400:
                break

        if resp is None:
            raise LLMError("Gemini request failed to start")
        if resp.status_code >= 400:
            raise LLMError(f"Gemini API error {last_err}")

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
    api_version = os.environ.get("GEMINI_API_VERSION", "v1beta").strip() or "v1beta"
    return GeminiProvider(api_key=api_key, model=model, api_version=api_version)

