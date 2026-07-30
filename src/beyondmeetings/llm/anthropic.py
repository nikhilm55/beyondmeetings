"""Claude adapter."""
from __future__ import annotations

import httpx

from ..models import MeetingNote
from .base import LLMProvider, parse_meeting_note
from .http import TruncatedResponseError, raise_for_status

API_URL = "https://api.anthropic.com/v1/messages"
DEFAULT_MODEL = "claude-opus-5"
TIMEOUT = 300.0


class AnthropicProvider(LLMProvider):
    def __init__(self, api_key: str, model: str = "", max_tokens: int = 16000):
        self.api_key = api_key
        self.model = model or DEFAULT_MODEL
        self.max_tokens = max_tokens

    def analyse(
        self, prompt: str, valid_candidate_ids: list[str] | None = None
    ) -> MeetingNote:
        response = httpx.post(
            API_URL,
            timeout=TIMEOUT,
            headers={
                "x-api-key": self.api_key,
                "anthropic-version": "2023-06-01",
                "content-type": "application/json",
            },
            json={
                "model": self.model,
                "max_tokens": self.max_tokens,
                "messages": [{"role": "user", "content": prompt}],
            },
        )
        raise_for_status("Anthropic", response)

        payload = response.json()
        if payload.get("stop_reason") == "max_tokens":
            raise TruncatedResponseError("Anthropic", self.max_tokens)

        blocks = payload.get("content") or []
        text = "".join(
            b.get("text") or "" for b in blocks if b.get("type") == "text"
        )
        return parse_meeting_note(text, valid_candidate_ids)
