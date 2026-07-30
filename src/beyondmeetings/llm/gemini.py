"""Gemini adapter.

The key travels in a header, never the query string — URLs end up in access
logs and proxy caches.
"""
from __future__ import annotations

import httpx

from ..models import MeetingNote
from .base import LLMProvider, ResponseParseError, parse_meeting_note
from .http import TruncatedResponseError, raise_for_status

BASE_URL = "https://generativelanguage.googleapis.com/v1beta/models"
DEFAULT_MODEL = "gemini-2.0-flash"
TIMEOUT = 300.0


class GeminiProvider(LLMProvider):
    def __init__(self, api_key: str, model: str = "", max_tokens: int = 16000):
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
        raise_for_status("Gemini", response)

        payload = response.json()
        candidates = payload.get("candidates") or []
        if not candidates:
            blocked = (payload.get("promptFeedback") or {}).get("blockReason")
            raise ResponseParseError(
                f"Gemini blocked the prompt ({blocked})."
                if blocked
                else "Gemini returned no candidates."
            )

        candidate = candidates[0]
        reason = candidate.get("finishReason")
        if reason == "MAX_TOKENS":
            raise TruncatedResponseError("Gemini", self.max_tokens)
        # A safety block omits `content` entirely — meeting transcripts discuss
        # conflict, personnel and health, so this is not exotic.
        if "content" not in candidate:
            raise ResponseParseError(
                f"Gemini returned no content (finishReason: {reason or 'unknown'}). "
                "Safety filters can block transcripts discussing personnel or health."
            )

        parts = (candidate.get("content") or {}).get("parts") or []
        text = "".join(p.get("text") or "" for p in parts)
        return parse_meeting_note(text, valid_candidate_ids)
