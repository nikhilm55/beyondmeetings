"""Insert tasks into the Task Board and keep its counters correct.

Counter arithmetic is code, not a model's job — this is the single largest
source of drift in the prose-driven pipeline this replaces.
"""
from __future__ import annotations

import re

from ..models import ActionItem, MeetingRef
from .paths import meeting_wikilink

PENDING_HEADER = re.compile(r"^> \[!todo\]\+ Pending — (\d+)\s*$", re.MULTILINE)
GLANCE_PENDING = re.compile(r"`(\d+) pending`")


def count_pending(text: str) -> int:
    match = PENDING_HEADER.search(text)
    if not match:
        raise ValueError("Task Board has no '> [!todo]+ Pending — N' callout")
    return int(match.group(1))


def update_counters(text: str, pending: int) -> str:
    text = PENDING_HEADER.sub(f"> [!todo]+ Pending — {pending}", text, count=1)
    return GLANCE_PENDING.sub(f"`{pending} pending`", text, count=1)


def _render_entry(item: ActionItem, ref: MeetingRef, description: str) -> str:
    tags = f"`{item.project}` · " if item.project else ""
    head = f"> > **=={item.task}==** · {tags}`{item.priority}`"

    detail = f"> > {description}"
    if item.owner:
        detail += f" — **{item.owner}**"
    if item.due:
        detail += f" · Due: {item.due}"
    detail += f" · {meeting_wikilink(ref)}"

    return f"{head}\n{detail}\n> >\n"


def add_tasks(
    text: str,
    items: list[ActionItem],
    ref: MeetingRef,
    description: str,
) -> str:
    if not items:
        return text

    current = count_pending(text)
    match = PENDING_HEADER.search(text)
    insert_at = match.end() + 1

    block = "".join(_render_entry(i, ref, description) for i in items)
    text = text[:insert_at] + block + text[insert_at:]
    return update_counters(text, current + len(items))
