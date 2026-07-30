"""ChatGPT adapter.

Uses the chat-completions API with native JSON mode, which removes most of
the fence-and-prose repair the parser would otherwise have to do.
"""
from __future__ import annotations

import httpx

from ..models import MeetingNote
from .base import LLMProvider, parse_meeting_note

API_URL = "https://api.openai.com/v1/chat/completions"
DEFAULT_MODEL = "gpt-4o"
TIMEOUT = 300.0

SYSTEM = "You analyse meeting transcripts and reply with a single JSON object."


class OpenAIProvider(LLMProvider):
    def __init__(self, api_key: str, model: str = "", max_tokens: int = 8000):
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
                "Authorization": f"Bearer {self.api_key}",
                "content-type": "application/json",
            },
            json={
                "model": self.model,
                "max_completion_tokens": self.max_tokens,
                "response_format": {"type": "json_object"},
                "messages": [
                    {"role": "system", "content": SYSTEM},
                    {"role": "user", "content": prompt},
                ],
            },
        )
        if response.status_code != 200:
            detail = response.json().get("error", {}).get("message", response.text)
            raise RuntimeError(f"OpenAI API error {response.status_code}: {detail}")

        choices = response.json().get("choices", [])
        text = choices[0]["message"]["content"] if choices else ""
        return parse_meeting_note(text, valid_candidate_ids)
