"""Local Ollama adapter.

No API key and nothing leaves the machine. Its failure modes are a stopped
daemon or an un-pulled model, so both get an actionable message rather than a
bare HTTP error.
"""
from __future__ import annotations

import httpx

from ..models import MeetingNote
from .base import LLMProvider, parse_meeting_note

DEFAULT_HOST = "http://localhost:11434"
DEFAULT_MODEL = "qwen2.5:14b"
TIMEOUT = 900.0  # local inference on CPU is slow


class OllamaProvider(LLMProvider):
    def __init__(self, model: str = "", host: str = DEFAULT_HOST):
        self.model = model or DEFAULT_MODEL
        self.host = (host or DEFAULT_HOST).rstrip("/")

    def analyse(
        self, prompt: str, valid_candidate_ids: list[str] | None = None
    ) -> MeetingNote:
        try:
            response = httpx.post(
                f"{self.host}/api/chat",
                timeout=TIMEOUT,
                json={
                    "model": self.model,
                    "format": "json",
                    "stream": False,
                    "messages": [{"role": "user", "content": prompt}],
                },
            )
        except httpx.HTTPError as exc:
            raise RuntimeError(
                f"Could not reach Ollama at {self.host} ({exc}). "
                "Start it with `ollama serve`."
            ) from exc

        if response.status_code == 404:
            raise RuntimeError(
                f"Ollama does not have model '{self.model}'. "
                f"Pull it with `ollama pull {self.model}`."
            )
        if response.status_code != 200:
            raise RuntimeError(
                f"Ollama error {response.status_code}: {response.text[:200]}"
            )

        text = response.json().get("message", {}).get("content", "")
        return parse_meeting_note(text, valid_candidate_ids)
