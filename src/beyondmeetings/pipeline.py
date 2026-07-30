"""Transcript in, vault updated.

Every write is deterministic. The provider's only influence is the content of
the MeetingNote it returns.
"""
from __future__ import annotations

import logging
from datetime import date
from pathlib import Path

from pydantic import ValidationError

from .config import Config
from .labels import provider_label, transcriber_label
from .llm.base import LLMProvider
from .models import MeetingRef
from .prompts import build_analysis_prompt
from .vault import followup, home, taskboard
from .vault import note as note_render
from .vault.paths import note_path

log = logging.getLogger(__name__)


def generate_notes(
    transcript: str,
    config: Config,
    provider: LLMProvider,
    meeting_date: str | None = None,
) -> Path:
    vault = Path(config.vault_path)
    meeting_date = meeting_date or date.today().isoformat()

    candidates = followup.gather_candidates(vault)
    prompt = build_analysis_prompt(
        transcript, meeting_date, candidates, config.projects, config.notes_language
    )
    result = provider.analyse(prompt, [c.ref.id for c in candidates])

    # A malformed date must not lose the whole note — fall back to the real
    # recording date and carry on.
    try:
        ref = MeetingRef(date=result.date or meeting_date, title=result.title)
    except ValidationError:
        log.warning(
            "model returned an unusable date %r; using %s", result.date, meeting_date
        )
        result.date = meeting_date
        ref = MeetingRef(date=meeting_date, title=result.title)

    # 1. Reciprocal follow-up link — resolved before rendering, so a link to a
    #    note that no longer exists degrades to standalone in the note too.
    previous = None
    if result.follow_up_of:
        candidate = MeetingRef.from_id(result.follow_up_of)
        if note_path(vault, candidate).exists():
            previous = candidate
        else:
            result.follow_up_of = None

    # 2. The meeting note itself.
    path = note_path(vault, ref)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        note_render.render_note(
            result,
            transcriber=transcriber_label(config.transcriber),
            provider=provider_label(config.provider),
        ),
        encoding="utf-8",
    )

    if previous:
        followup.append_followup_backlink(note_path(vault, previous), ref)

    # 3. Task Board — skipped entirely for informal/personal calls.
    board_path = vault / "Tasks" / "Task Board.md"
    board = board_path.read_text(encoding="utf-8")
    if result.action_items and not result.is_informal:
        board = taskboard.add_tasks(
            board, result.action_items, ref, result.one_line_summary or result.title
        )
        board_path.write_text(board, encoding="utf-8")
    pending = taskboard.count_pending(board)

    # 4. Home.md — always updated, counters kept in step with the board.
    home_path = vault / "Home.md"
    text = home_path.read_text(encoding="utf-8")
    project = next((t for t in result.tags if t.lower() != "meeting"), None)
    text = home.add_recent_meeting(
        text, ref, result.title, project,
        result.one_line_summary or result.executive_summary,
        previous=previous,
        previous_display=previous.title if previous else None,
    )
    text = home.sync_counters(text, pending)
    text = home.touch_updated(text, date.today().isoformat())
    home_path.write_text(text, encoding="utf-8")

    return path
