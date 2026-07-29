"""Follow-up candidate gathering and reciprocal linking.

The LLM never browses the vault. Python collects candidates from the last N
days and passes them in the prompt; the model returns one id or null.
"""
from __future__ import annotations

import re
from datetime import date, timedelta
from pathlib import Path

from pydantic import BaseModel

from ..models import MeetingRef
from .paths import meeting_wikilink, meetings_dir

DATE_FOLDER = re.compile(r"^\d{4}-\d{2}-\d{2}$")
SUMMARY = re.compile(
    r"^## Executive Summary\s*\n(.+?)(?=\n##|\n---|\Z)", re.DOTALL | re.MULTILINE
)
TAG_LINE = re.compile(r"^\s+- (.+)$", re.MULTILINE)


class Candidate(BaseModel):
    ref: MeetingRef
    tags: list[str] = []
    executive_summary: str = ""


def _parse(path: Path, folder: str) -> Candidate:
    text = path.read_text(encoding="utf-8", errors="replace")
    front = text.split("---", 2)[1] if text.startswith("---") else ""
    tags = [t.strip() for t in TAG_LINE.findall(front) if t.strip() != "meeting"]
    match = SUMMARY.search(text)
    summary = match.group(1).strip() if match else ""
    return Candidate(
        ref=MeetingRef(date=folder, title=path.stem),
        tags=tags,
        executive_summary=summary,
    )


def gather_candidates(vault: Path, days: int = 30, limit: int = 12) -> list[Candidate]:
    root = meetings_dir(vault)
    if not root.is_dir():
        return []

    cutoff = date.today() - timedelta(days=days)
    found: list[Candidate] = []
    for folder in sorted(root.iterdir(), reverse=True):
        if not folder.is_dir() or not DATE_FOLDER.match(folder.name):
            continue
        try:
            if date.fromisoformat(folder.name) < cutoff:
                continue
        except ValueError:
            continue
        for note in sorted(folder.glob("*.md")):
            found.append(_parse(note, folder.name))
            if len(found) >= limit:
                return found
    return found


def _split_frontmatter(text: str) -> tuple[str, str]:
    """Return (frontmatter, body). Frontmatter is '' when there is none.

    Splitting matters: a naive search for a trailing '---' finds the
    frontmatter's own closing fence and inserts content inside it.
    """
    if not text.startswith("---\n"):
        return "", text
    end = text.find("\n---", 3)
    if end == -1:
        return "", text
    close = end + len("\n---")
    if text[close:close + 1] == "\n":
        close += 1
    return text[:close], text[close:]


def append_followup_backlink(previous_note: Path, new: MeetingRef) -> None:
    """Record the forward link in the previous meeting's note."""
    text = previous_note.read_text(encoding="utf-8")
    line = f"- Followed up in: {meeting_wikilink(new)}"
    if line in text:
        return

    front, body = _split_frontmatter(text)

    if "## Follow-ups" in body:
        head, _, tail = body.partition("## Follow-ups\n")
        existing, sep, rest = tail.partition("\n---")
        body = head + "## Follow-ups\n" + existing.rstrip("\n") + "\n" + line + "\n" + sep + rest
    else:
        before, sep, rest = body.rpartition("\n---")
        if sep:
            body = before.rstrip("\n") + f"\n\n## Follow-ups\n{line}\n" + sep + rest
        else:
            body = body.rstrip("\n") + f"\n\n## Follow-ups\n{line}\n"

    previous_note.write_text(front + body, encoding="utf-8")
