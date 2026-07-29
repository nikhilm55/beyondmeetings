from pathlib import Path

from beyondmeetings.models import MeetingRef
from beyondmeetings.vault.paths import (
    meeting_wikilink,
    note_path,
    safe_filename,
)


def test_safe_filename_replaces_em_dash_with_hyphen():
    assert safe_filename("Phase 4 — Resourcing Plan") == "Phase 4 - Resourcing Plan"


def test_safe_filename_strips_path_separators():
    assert safe_filename("Q3/Q4 Planning") == "Q3-Q4 Planning"


def test_safe_filename_strips_illegal_characters():
    assert safe_filename('Review: "scope" <draft>?') == "Review - scope draft"


def test_safe_filename_collapses_whitespace():
    assert safe_filename("Too    many   spaces") == "Too many spaces"


def test_safe_filename_never_returns_empty():
    assert safe_filename("///") == "Untitled Meeting"


def test_note_path_uses_date_folder_and_bare_filename():
    path = note_path(Path("/vault"), MeetingRef(date="2026-07-30", title="Standup"))
    assert path == Path("/vault/Meetings/2026-07-30/Standup.md")


def test_meeting_wikilink_is_full_path_without_extension():
    ref = MeetingRef(date="2026-07-30", title="Standup")
    assert meeting_wikilink(ref) == "[[Meetings/2026-07-30/Standup]]"


def test_meeting_wikilink_with_display_title_uses_pipe():
    ref = MeetingRef(date="2026-07-30", title="Phase 4 - Plan")
    link = meeting_wikilink(ref, display="Phase 4 — Plan")
    assert link == "[[Meetings/2026-07-30/Phase 4 - Plan|Phase 4 — Plan]]"
