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

# Ollama defaults to a 4096-token context and silently discards whatever does
# not fit — a one-hour transcript is ~18k tokens, so most of the meeting would
# vanish and the model would confidently summarise only the tail.
DEFAULT_NUM_CTX = 32768
CHARS_PER_TOKEN = 3.5  # deliberately pessimistic for code-mixed speech


def estimate_tokens(text: str) -> int:
    return int(len(text) / CHARS_PER_TOKEN)


class OllamaProvider(LLMProvider):
    def __init__(
        self, model: str = "", host: str = DEFAULT_HOST, num_ctx: int = DEFAULT_NUM_CTX
    ):
        self.model = model or DEFAULT_MODEL
        self.host = (host or DEFAULT_HOST).rstrip("/")
        self.num_ctx = num_ctx or DEFAULT_NUM_CTX

    def analyse(
        self, prompt: str, valid_candidate_ids: list[str] | None = None
    ) -> MeetingNote:
        # Silent truncation would produce a confident, well-formed, wrong note
        # that nothing downstream could detect. Refuse instead.
        estimated = estimate_tokens(prompt)
        if estimated > self.num_ctx:
            raise RuntimeError(
                f"This transcript is roughly {estimated:,} tokens but Ollama is "
                f"configured for {self.num_ctx:,}. Ollama would silently drop the "
                "start of the meeting. Raise ollama_num_ctx in your config, or "
                "use a hosted provider for long meetings."
            )

        try:
            response = httpx.post(
                f"{self.host}/api/chat",
                timeout=TIMEOUT,
                json={
                    "model": self.model,
                    "format": "json",
                    "stream": False,
                    "options": {"num_ctx": self.num_ctx},
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
