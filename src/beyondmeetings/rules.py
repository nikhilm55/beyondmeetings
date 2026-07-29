"""Generate agent rules files from a single template.

Three filenames, one body. They are thin drivers over the CLI: behaviour
lives in Python so every agent produces identical notes. Duplicated prose
rots — the original project's AGENTS.md drifted months out of date from its
own CLAUDE.md.
"""
from __future__ import annotations

from pathlib import Path

FILENAMES = ("CLAUDE.md", "AGENTS.md", "GEMINI.md")

TEMPLATE = """# beyondMeetings — Agent Instructions

<!-- GENERATED FILE — do not edit. Regenerate with `beyondmeetings setup`. -->
<!-- CLAUDE.md, AGENTS.md and GEMINI.md are identical copies of one template. -->

beyondMeetings records meetings, transcribes them, and writes structured notes
into an Obsidian vault. **All behaviour lives in the `beyondmeetings` command.**
Your job is to run it at the right moment — never to reimplement it.

## When the user says "start recording"

Run this immediately:

```bash
beyondmeetings start "[meeting name]"
```

**Never ask for a meeting name.** A meeting is already under way and every
second spent asking is audio lost. If no name was given, run `beyondmeetings
start` with no argument — it assigns a timestamp placeholder, and the real
title is derived from the transcript when notes are generated.

Then confirm: "Recording started. Tell me when to stop."

## When the user says "stop recording" or "generate notes"

```bash
beyondmeetings stop
```

This does everything: stops capture, transcribes, analyses the transcript,
writes the meeting note, adds tasks to the task board, updates the dashboard,
and links follow-up meetings. It prints the transcript and note paths.

Long meetings can take a few minutes if the transcription API is rate-limited.
That is expected — do not re-run it.

## Regenerating notes for an existing transcript

```bash
beyondmeetings notes /path/to/transcript.txt
```

## Checking the installation

```bash
beyondmeetings doctor
```

## Vault conventions

The vault is at `{vault_path}`.

| What | Where |
|---|---|
| Meeting notes | `Meetings/YYYY-MM-DD/[Meeting Name].md` |
| Task board | `Tasks/Task Board.md` |
| Dashboard | `Home.md` |

Notes are linked by full path with the date folder:
`[[Meetings/YYYY-MM-DD/Meeting Name]]`. The filename itself carries no date
prefix — the folder is the date.

**Do not hand-edit the task board counters.** They are computed.
"""


def render_rules(vault_path: str) -> str:
    return TEMPLATE.format(vault_path=vault_path)


def write_rules(target_dir: Path, vault_path: str) -> list[Path]:
    target_dir = Path(target_dir)
    target_dir.mkdir(parents=True, exist_ok=True)
    body = render_rules(vault_path)
    written = []
    for name in FILENAMES:
        path = target_dir / name
        path.write_text(body, encoding="utf-8")
        written.append(path)
    return written
