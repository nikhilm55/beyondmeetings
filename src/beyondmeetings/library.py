"""Read-only helpers for the built-in notes library UI."""
from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path


TASK_HEAD = re.compile(
    r"^> > \*\*==(?P<title>.+?)==\*\* · "
    r"(?:(?:`(?P<project>[^`]+)` · ))?`(?P<priority>[^`]+)`$"
)
OWNER = re.compile(r" — \*\*(.+?)\*\*")
DUE = re.compile(r" · Due: (\d{4}-\d{2}-\d{2})")
MEETING = re.compile(r"\[\[(Meetings/[^\]|]+)(?:\|[^\]]+)?\]\]")


def resolve_markdown(library: Path, requested: str) -> Path:
    """Resolve a UI note link without allowing traversal or arbitrary reads."""
    library = Path(library).resolve()
    relative = requested.strip().replace("\\", "/").lstrip("/")
    if not relative.endswith(".md"):
        relative += ".md"
    candidate = (library / relative).resolve()
    if not candidate.is_relative_to(library) or candidate.suffix.lower() != ".md":
        raise ValueError("note path is outside the local library")
    return candidate


def list_tasks(library: Path) -> list[dict]:
    """Parse deterministic task-board entries into data for the desktop UI."""
    board = Path(library) / "Tasks" / "Task Board.md"
    if not board.is_file():
        return []

    lines = board.read_text(encoding="utf-8", errors="replace").splitlines()
    tasks: list[dict] = []
    for index, line in enumerate(lines):
        match = TASK_HEAD.match(line)
        if not match:
            continue
        detail = lines[index + 1].removeprefix("> > ") if index + 1 < len(lines) else ""
        owner = OWNER.search(detail)
        due = DUE.search(detail)
        meeting = MEETING.search(detail)
        description = detail.split(" — **", 1)[0].split(" · Due:", 1)[0]
        tasks.append({
            **match.groupdict(),
            "owner": owner.group(1) if owner else "",
            "due": due.group(1) if due else "",
            "meeting": meeting.group(1) if meeting else "",
            "description": description,
        })
    return tasks


def open_library_folder(
    library: Path,
    platform: str | None = None,
    spawn=None,
) -> None:
    """Open the local library in the platform's normal file manager."""
    library = Path(library)
    library.mkdir(parents=True, exist_ok=True)
    platform = platform if platform is not None else sys.platform
    spawn = spawn or subprocess.Popen

    if platform == "darwin":
        command = ["open", str(library)]
    elif platform == "win32":
        command = ["explorer", str(library)]
    else:
        command = ["xdg-open", str(library)]

    spawn(
        command,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=platform != "win32",
    )
