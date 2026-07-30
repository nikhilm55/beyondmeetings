"""Filename sanitising and wikilink construction.

Obsidian note filenames drop the date prefix — the date is the folder — and
links are always full-path: [[Meetings/YYYY-MM-DD/Title]].
"""
from __future__ import annotations

import re
from pathlib import Path

from ..models import MeetingRef

_ILLEGAL = r'["<>?*|\\]'
_FALLBACK = "Untitled Meeting"


def safe_filename(title: str) -> str:
    # Separators become hyphens so the title still reads correctly; everything
    # else that is illegal in a filename is simply dropped.
    name = title.replace("—", "-").replace("–", "-")
    name = name.replace("/", "-").replace(":", " -")
    name = re.sub(_ILLEGAL, "", name)
    name = re.sub(r"\s+", " ", name).strip(" .-")
    return name or _FALLBACK


def meetings_dir(vault: Path) -> Path:
    return vault / "Meetings"


def note_path(vault: Path, ref: MeetingRef) -> Path:
    """Resolve a note path, asserting it stays inside the vault.

    MeetingRef.date is already pattern-validated; this is the belt-and-braces
    check at the point of the actual write, because the transcript that
    produced it is untrusted text.
    """
    vault = Path(vault)
    path = meetings_dir(vault) / ref.date / f"{safe_filename(ref.title)}.md"
    resolved = path.resolve()
    if not resolved.is_relative_to(meetings_dir(vault).resolve()):
        raise ValueError(f"refusing to write outside the vault: {resolved}")
    return path


def meeting_wikilink(ref: MeetingRef, display: str | None = None) -> str:
    target = f"Meetings/{ref.date}/{safe_filename(ref.title)}"
    if display and display != safe_filename(ref.title):
        return f"[[{target}|{display}]]"
    return f"[[{target}]]"
