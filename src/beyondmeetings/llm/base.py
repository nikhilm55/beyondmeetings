"""Provider interface and response parsing.

Providers vary in how faithfully they honour "return only JSON". Extraction
lives here so every adapter benefits and none reimplements it. Note that this
is extraction, not repair — malformed JSON is reported, never patched up.
"""
from __future__ import annotations

import json
from abc import ABC, abstractmethod

from pydantic import ValidationError

from ..models import MeetingNote


class ResponseParseError(RuntimeError):
    """The model's output could not be coerced into a MeetingNote."""


def _json_candidates(raw: str) -> list[str]:
    """Every plausible JSON object in the output, best guess last.

    Models sometimes echo the schema in one fenced block and answer in the
    next, so a single "first block wins" rule picked the schema. Each
    candidate is tried in turn instead.
    """
    text = raw.strip()
    candidates: list[str] = []

    if "```" in text:
        blocks = text.split("```")
        for block in blocks[1::2]:
            body = block
            first, _, rest = block.partition("\n")
            if first.strip().lower() in {"json", "json5", "jsonc"}:
                body = rest
            if "{" in body:
                candidates.append(body)

    candidates.append(text)

    extracted = []
    for candidate in candidates:
        start = candidate.find("{")
        end = candidate.rfind("}")
        if start != -1 and end > start:
            extracted.append(candidate[start : end + 1])
    return extracted


def parse_meeting_note(
    raw: str, valid_candidate_ids: list[str] | None = None
) -> MeetingNote:
    """Parse model output into a MeetingNote.

    `follow_up_of` is cleared unless it names one of the candidates that were
    supplied in the prompt — the model cannot invent a link to a note that
    does not exist.
    """
    candidates = _json_candidates(raw)
    if not candidates:
        raise ResponseParseError(
            f"no JSON object found in model output: {raw[:200]!r}"
        )

    note = None
    last_error: Exception | None = None
    for payload in candidates:
        try:
            note = MeetingNote(**json.loads(payload))
            break
        except (json.JSONDecodeError, ValidationError, TypeError) as exc:
            last_error = exc

    if note is None:
        raise ResponseParseError(
            f"could not read a meeting note from the model's output: {last_error}"
        )

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
