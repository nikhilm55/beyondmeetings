"""Read the vault to list past meetings for the app page."""
from __future__ import annotations

import re
from datetime import date, timedelta
from pathlib import Path

from .vault.paths import meetings_dir

DATE_FOLDER = re.compile(r"^\d{4}-\d{2}-\d{2}$")
SUMMARY = re.compile(
    r"^## Executive Summary\s*\n(.+?)(?=\n##|\n---|\Z)", re.DOTALL | re.MULTILINE
)
TAG_LINE = re.compile(r"^\s+- (.+)$", re.MULTILINE)
TASK_LINE = re.compile(r"^- \[ \] ", re.MULTILINE)
RECORDED_AT = re.compile(r'^recorded_at:\s*["\']?(.+?)["\']?\s*$', re.MULTILINE)
MARKDOWN = re.compile(r"[`*_>#\[\]]")
WORDS = re.compile(r"[a-z0-9]+")
STOP_WORDS = {
    "a", "about", "all", "an", "and", "ask", "did", "do", "file", "files",
    "find", "for", "from", "give", "in", "is", "last", "meeting", "meetings",
    "me", "my", "notes", "of", "on", "our", "show", "the", "to", "was",
    "we", "what", "when", "where", "with",
}
MONTHS = {
    "january": "01", "february": "02", "march": "03", "april": "04",
    "may": "05", "june": "06", "july": "07", "august": "08",
    "september": "09", "october": "10", "november": "11", "december": "12",
}


def _read(path: Path, folder: str) -> dict:
    text = path.read_text(encoding="utf-8", errors="replace")
    front = text.split("---", 2)[1] if text.startswith("---") else ""
    tags = [t.strip() for t in TAG_LINE.findall(front) if t.strip() != "meeting"]
    match = SUMMARY.search(text)
    recorded = RECORDED_AT.search(front)
    return {
        "title": path.stem,
        "date": folder,
        "summary": match.group(1).strip() if match else "",
        "project": tags[0] if tags else "",
        "tasks": len(TASK_LINE.findall(text)),
        "recorded_at": recorded.group(1).strip() if recorded else "",
        "link": f"Meetings/{folder}/{path.stem}",
    }


def list_meetings(vault: Path, limit: int = 100) -> list[dict]:
    root = meetings_dir(Path(vault))
    if not root.is_dir():
        return []

    found: list[dict] = []
    for folder in sorted(root.iterdir(), reverse=True):
        if not folder.is_dir() or not DATE_FOLDER.match(folder.name):
            continue
        for note in sorted(folder.glob("*.md")):
            found.append(_read(note, folder.name))
            if len(found) >= limit:
                return found
    return found


def _search_terms(query: str, today: date) -> list[str]:
    lowered = query.casefold()
    words = WORDS.findall(lowered)
    terms = [word for word in words if word not in STOP_WORDS and len(word) > 1]
    if "today" in words:
        terms.append(today.isoformat())
    if "yesterday" in words:
        terms.append((today - timedelta(days=1)).isoformat())
    for month, number in MONTHS.items():
        if month in words:
            terms.extend((month, number))
    return list(dict.fromkeys(terms))


def _plain_excerpt(text: str, terms: list[str], limit: int = 240) -> str:
    body = text.split("---", 2)[-1] if text.startswith("---") else text
    lines = [
        MARKDOWN.sub("", line).strip()
        for line in body.splitlines()
        if line.strip() and not line.lstrip().startswith("Transcribed with")
    ]
    plain = " ".join(line for line in lines if line)
    lowered = plain.casefold()
    positions = [lowered.find(term) for term in terms if lowered.find(term) >= 0]
    start = max(0, (min(positions) if positions else 0) - 70)
    excerpt = plain[start : start + limit].strip()
    if start:
        excerpt = "…" + excerpt
    if start + limit < len(plain):
        excerpt += "…"
    return excerpt


def search_meetings(
    vault: Path,
    query: str,
    limit: int = 6,
    today: date | None = None,
) -> dict:
    """Retrieve old notes locally and return concise, source-linked results."""
    query = " ".join(query.split()).strip()
    if not query:
        return {"answer": "Ask me to find a meeting, topic, person or date.", "sources": []}

    meetings = list_meetings(vault, limit=500)
    terms = _search_terms(query, today or date.today())
    recent_intent = not terms or any(
        phrase in query.casefold() for phrase in ("latest", "last meeting", "recent")
    )
    ranked: list[tuple[int, dict]] = []

    for index, meeting in enumerate(meetings):
        note = (Path(vault) / f"{meeting['link']}.md").resolve()
        if not note.is_file():
            continue
        text = note.read_text(encoding="utf-8", errors="replace")
        title = meeting["title"].casefold()
        summary = meeting["summary"].casefold()
        haystack = f"{meeting['date']} {meeting['project']} {text}".casefold()
        score = max(0, 5 - index) if recent_intent else 0
        compact_query = query.casefold()
        if compact_query in title:
            score += 30
        elif compact_query in haystack:
            score += 18
        for term in terms:
            if term in title:
                score += 10
            elif term in summary:
                score += 6
            elif term in haystack:
                score += 2
        if meeting["tasks"] and any(term in {"action", "items", "task", "tasks"} for term in terms):
            score += 8
        if score <= 0:
            continue
        source = dict(meeting)
        source["excerpt"] = _plain_excerpt(text, terms)
        ranked.append((score, source))

    sources = [source for _, source in sorted(
        ranked, key=lambda row: (row[0], row[1]["date"]), reverse=True
    )[:limit]]
    if not sources:
        answer = f'I could not find a saved meeting matching “{query}”. Try a topic, person, project or date.'
    elif len(sources) == 1:
        answer = (
            f'I found one relevant meeting: “{sources[0]["title"]}” from '
            f'{sources[0]["date"]}. {sources[0]["summary"]}'
        ).strip()
    else:
        answer = f"I found {len(sources)} relevant meetings. The closest matches are listed below."
    return {"answer": answer, "sources": sources}
