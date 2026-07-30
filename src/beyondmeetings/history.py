"""Read the vault to list past meetings for the app page."""
from __future__ import annotations

import re
from pathlib import Path

from .vault.paths import meetings_dir

DATE_FOLDER = re.compile(r"^\d{4}-\d{2}-\d{2}$")
SUMMARY = re.compile(
    r"^## Executive Summary\s*\n(.+?)(?=\n##|\n---|\Z)", re.DOTALL | re.MULTILINE
)
TAG_LINE = re.compile(r"^\s+- (.+)$", re.MULTILINE)
TASK_LINE = re.compile(r"^- \[ \] ", re.MULTILINE)


def _read(path: Path, folder: str) -> dict:
    text = path.read_text(encoding="utf-8", errors="replace")
    front = text.split("---", 2)[1] if text.startswith("---") else ""
    tags = [t.strip() for t in TAG_LINE.findall(front) if t.strip() != "meeting"]
    match = SUMMARY.search(text)
    return {
        "title": path.stem,
        "date": folder,
        "summary": match.group(1).strip() if match else "",
        "project": tags[0] if tags else "",
        "tasks": len(TASK_LINE.findall(text)),
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
