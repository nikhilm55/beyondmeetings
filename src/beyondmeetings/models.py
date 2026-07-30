"""The data contract between the LLM and the vault writers.

The LLM returns exactly one MeetingNote as JSON. Everything downstream is
deterministic Python that reads this object — no model output ever reaches
the filesystem unvalidated.
"""
from __future__ import annotations

from typing import Annotated, Literal

from pydantic import BaseModel, Field, StringConstraints

Priority = Literal["HIGH", "MEDIUM", "LOW"]

# `date` becomes a directory name, so it is validated as a value and not just
# as a type. A model returning "2026-7-9" produced a folder the history and
# follow-up scanners then rejected — the note existed but was invisible; and
# "../../tmp" escaped the vault entirely.
IsoDate = Annotated[str, StringConstraints(pattern=r"^\d{4}-\d{2}-\d{2}$")]


class MeetingRef(BaseModel):
    """Identifies a meeting note by its date folder and display title."""

    date: IsoDate
    title: str

    @property
    def id(self) -> str:
        return f"{self.date}/{self.title}"

    @classmethod
    def from_id(cls, value: str) -> "MeetingRef":
        date, sep, title = value.partition("/")
        if not sep or not title:
            raise ValueError(f"malformed meeting id: {value!r}")
        return cls(date=date, title=title)


class ActionItem(BaseModel):
    task: str
    owner: str | None = None
    due: str | None = None
    project: str | None = None
    priority: Priority = "MEDIUM"


class Section(BaseModel):
    """Free-form narrative content only.

    Decisions, open questions, risks and action items are typed fields on
    MeetingNote and must never be duplicated here — each is rendered under
    its own heading by vault/note.py.
    """

    heading: str
    bullets: list[str] = Field(default_factory=list)


class MeetingNote(BaseModel):
    title: str
    date: str
    tags: list[str] = Field(default_factory=list)
    attendees: list[str] = Field(default_factory=list)
    executive_summary: str
    sections: list[Section] = Field(default_factory=list)
    decisions: list[str] = Field(default_factory=list)
    open_questions: list[str] = Field(default_factory=list)
    risks: list[str] = Field(default_factory=list)
    follow_ups: list[str] = Field(default_factory=list)
    action_items: list[ActionItem] = Field(default_factory=list)
    transcription_note: str | None = None
    is_informal: bool = False
    follow_up_of: str | None = None
    one_line_summary: str = ""
