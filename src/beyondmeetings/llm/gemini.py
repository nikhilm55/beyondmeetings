"""Gemini adapter.

The key travels in a header, never the query string — URLs end up in access
logs and proxy caches.
"""
from __future__ import annotations

import httpx

from ..models import MeetingNote
from .base import LLMProvider, parse_meeting_note

BASE_URL = "https://generativelanguage.googleapis.com/v1beta/models"
DEFAULT_MODEL = "gemini-2.0-flash"
TIMEOUT = 300.0


class GeminiProvider(LLMProvider):
    def __init__(self, api_key: str, model: str = "", max_tokens: int = 8000):
        self.api_key = api_key
        self.model = model or DEFAULT_MODEL
        self.max_tokens = max_tokens

    def analyse(
        self, prompt: str, valid_candidate_ids: list[str] | None = None
    ) -> MeetingNote:
        response = httpx.post(
            f"{BASE_URL}/{self.model}:generateContent",
            timeout=TIMEOUT,
            headers={
                "x-goog-api-key": self.api_key,
                "content-type": "application/json",
            },
            json={
                "contents": [{"parts": [{"text": prompt}]}],
                "generationConfig": {
                    "responseMimeType": "application/json",
                    "maxOutputTokens": self.max_tokens,
                },
            },
        )
        if response.status_code != 200:
            detail = response.json().get("error", {}).get("message", response.text)
            raise RuntimeError(f"Gemini API error {response.status_code}: {detail}")

        candidates = response.json().get("candidates", [])
        parts = candidates[0]["content"]["parts"] if candidates else []
        text = "".join(p.get("text", "") for p in parts)
        return parse_meeting_note(text, valid_candidate_ids)
