"""Provider interface and response parsing.

Providers vary in how faithfully they honour "return only JSON". Repair
lives here so every adapter benefits and none reimplements it.
"""
from __future__ import annotations

import json
from abc import ABC, abstractmethod

from pydantic import ValidationError

from ..models import MeetingNote


class ResponseParseError(RuntimeError):
    """The model's output could not be coerced into a MeetingNote."""


def _extract_json_object(raw: str) -> str:
    text = raw.strip()
    if "```" in text:
        blocks = text.split("```")
        for block in blocks[1::2]:
            candidate = block.split("\n", 1)[-1] if block.startswith("json") else block
            if "{" in candidate:
                text = candidate
                break
    start = text.find("{")
    end = text.rfind("}")
    if start == -1 or end == -1 or end < start:
        raise ResponseParseError(f"no JSON object found in model output: {raw[:200]!r}")
    return text[start : end + 1]


def parse_meeting_note(
    raw: str, valid_candidate_ids: list[str] | None = None
) -> MeetingNote:
    """Parse model output into a MeetingNote.

    `follow_up_of` is cleared unless it names one of the candidates that were
    supplied in the prompt — the model cannot invent a link to a note that
    does not exist.
    """
    payload = _extract_json_object(raw)
    try:
        data = json.loads(payload)
    except json.JSONDecodeError as exc:
        raise ResponseParseError(f"invalid JSON from model: {exc}") from exc

    try:
        note = MeetingNote(**data)
    except ValidationError as exc:
        raise ResponseParseError(f"model output failed validation: {exc}") from exc

    if note.follow_up_of and valid_candidate_ids is not None:
        if note.follow_up_of not in valid_candidate_ids:
            note.follow_up_of = None
    return note


class LLMProvider(ABC):
    """One call in, one MeetingNote out."""

    @abstractmethod
    def analyse(
        self, prompt: str, valid_candidate_ids: list[str] | None = None
    ) -> MeetingNote:
        ...
