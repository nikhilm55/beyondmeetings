"""Home.md is the dashboard linking both meetings and tasks.

It must never drift from Task Board.md — sync_counters() is called in the
same pass as every task insert.
"""
from __future__ import annotations

import re

from ..models import MeetingRef
from .paths import meeting_wikilink

RECENT_HEADER = re.compile(r"^> \[!example\]\+ Recent\s*$", re.MULTILINE)
PENDING_HEADER = re.compile(r"^> \[!todo\]\+ Pending — (\d+)\s*$", re.MULTILINE)
GLANCE_PENDING = re.compile(r"`(\d+) pending`")
UPDATED = re.compile(r"^updated: .*$", re.MULTILINE)


def sync_counters(text: str, pending: int) -> str:
    text = PENDING_HEADER.sub(f"> [!todo]+ Pending — {pending}", text, count=1)
    return GLANCE_PENDING.sub(f"`{pending} pending`", text, count=1)


def touch_updated(text: str, today: str) -> str:
    return UPDATED.sub(f"updated: {today}", text, count=1)


def add_recent_meeting(
    text: str,
    ref: MeetingRef,
    display: str,
    project: str | None,
    description: str,
    previous: MeetingRef | None = None,
    previous_display: str | None = None,
) -> str:
    match = RECENT_HEADER.search(text)
    if not match:
        raise ValueError("Home.md has no '> [!example]+ Recent' callout")

    line = f"> **{meeting_wikilink(ref, display)}**"
    if project:
        line += f" · {project}"
    line += f" · {description}"
    if previous:
        line += f" · ↳ follow-up to {meeting_wikilink(previous, previous_display)}"
    line += "\n"

    insert_at = match.end() + 1
    return text[:insert_at] + line + text[insert_at:]
