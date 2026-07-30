"""Insert tasks into the Task Board and keep its counters correct.

Counter arithmetic is code, not a model's job — this is the single largest
source of drift in the prose-driven pipeline this replaces.
"""
from __future__ import annotations

import re

from ..models import ActionItem, MeetingRef
from .paths import meeting_wikilink

# [ \t]* rather than \s* — under MULTILINE, \s* matches newlines and would
# swallow a blank line that follows the header.
PENDING_HEADER = re.compile(r"^> \[!todo\]\+ Pending — (\d+)[ \t]*$", re.MULTILINE)
GLANCE_PENDING = re.compile(r"`(\d+) pending`")


def count_pending(text: str) -> int:
    match = PENDING_HEADER.search(text)
    if not match:
        raise ValueError("Task Board has no '> [!todo]+ Pending — N' callout")
    return int(match.group(1))


def update_counters(text: str, pending: int) -> str:
    text = PENDING_HEADER.sub(f"> [!todo]+ Pending — {pending}", text, count=1)
    return GLANCE_PENDING.sub(f"`{pending} pending`", text, count=1)


def _one_line(value: str) -> str:
    """Callout nesting breaks if a value contains a newline."""
    return " ".join(str(value).split())


def _render_entry(item: ActionItem, ref: MeetingRef, description: str) -> str:
    tags = f"`{item.project}` · " if item.project else ""
    head = f"> > **=={_one_line(item.task)}==** · {tags}`{item.priority}`"

    detail = f"> > {_one_line(description)}"
    if item.owner:
        detail += f" — **{item.owner}**"
    if item.due:
        detail += f" · Due: {item.due}"
    detail += f" · {meeting_wikilink(ref)}"

    return f"{head}\n{detail}\n> >\n"


def _already_present(text: str, item: ActionItem, ref: MeetingRef) -> bool:
    """Same task name, same meeting — this entry is already on the board."""
    return f"**=={item.task}==**" in text and meeting_wikilink(ref) in text


def add_tasks(
    text: str,
    items: list[ActionItem],
    ref: MeetingRef,
    description: str,
) -> str:
    """Idempotent: re-running for the same meeting will not duplicate tasks.

    generate_notes is not transactional, so a failure after the board write
    sends the user to Regenerate — which used to add every task a second time
    and bump the counter again.
    """
    fresh = [i for i in items if not _already_present(text, i, ref)]
    if not fresh:
        return text

    current = count_pending(text)
    match = PENDING_HEADER.search(text)
    # +1 steps over the header's newline. Clamp so a header that is the final
    # line without a trailing newline does not concatenate onto itself.
    insert_at = min(match.end() + 1, len(text))
    if insert_at == len(text) and not text.endswith("\n"):
        text += "\n"
        insert_at = len(text)

    block = "".join(_render_entry(i, ref, description) for i in fresh)
    text = text[:insert_at] + block + text[insert_at:]
    return update_counters(text, current + len(fresh))
