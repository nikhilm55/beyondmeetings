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


FOLLOWUPS_HEADING = re.compile(r"^## Follow-ups[ \t]*$", re.MULTILINE)
SECTION_END = re.compile(r"^(?:## |---[ \t]*$)", re.MULTILINE)
FENCE = re.compile(r"^(```|~~~)", re.MULTILINE)


def _fenced_spans(text: str) -> list[tuple[int, int]]:
    """Ranges inside ``` fences, so headings quoted in code are ignored."""
    marks = [m.start() for m in FENCE.finditer(text)]
    return [(marks[i], marks[i + 1]) for i in range(0, len(marks) - 1, 2)]


def _outside_fences(match_start: int, spans: list[tuple[int, int]]) -> bool:
    return not any(start <= match_start < end for start, end in spans)


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
    spans = _fenced_spans(body)

    heading = next(
        (m for m in FOLLOWUPS_HEADING.finditer(body) if _outside_fences(m.start(), spans)),
        None,
    )

    if heading is not None:
        # The section ends at the NEXT heading, not at the footer rule. Looking
        # for the rule swallowed every section in between and appended the link
        # under whatever heading happened to come last.
        after = heading.end()
        following = next(
            (
                m
                for m in SECTION_END.finditer(body, after + 1)
                if _outside_fences(m.start(), spans)
            ),
            None,
        )
        end = following.start() if following else len(body)
        section = body[after:end].rstrip("\n")
        body = body[:after] + section + "\n" + line + "\n\n" + body[end:]
    else:
        footer = [
            m for m in SECTION_END.finditer(body)
            if body[m.start():m.start() + 3] == "---" and _outside_fences(m.start(), spans)
        ]
        block = f"## Follow-ups\n{line}\n"
        if footer:
            cut = footer[-1].start()
            body = body[:cut].rstrip("\n") + f"\n\n{block}\n" + body[cut:]
        else:
            body = body.rstrip("\n") + f"\n\n{block}"

    previous_note.write_text(front + body, encoding="utf-8")
