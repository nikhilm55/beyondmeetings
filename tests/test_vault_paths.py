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


# --- Review finding #5: model-controlled date reached the filesystem ---

import pytest
from pydantic import ValidationError


def test_meeting_ref_rejects_a_traversal_date():
    with pytest.raises(ValidationError):
        MeetingRef(date="../../../../tmp/pwned", title="Standup")


def test_meeting_ref_rejects_a_non_iso_date():
    """'2026-7-9' wrote a folder the history scanner then ignored."""
    for bad in ("2026-7-9", "June 22 2026", "", "2026/07/30"):
        with pytest.raises(ValidationError):
            MeetingRef(date=bad, title="Standup")


def test_meeting_ref_accepts_an_iso_date():
    assert MeetingRef(date="2026-07-30", title="Standup").date == "2026-07-30"


def test_note_path_refuses_to_escape_the_vault(tmp_path):
    """Belt-and-braces: even if validation were bypassed, the write is refused."""
    ref = MeetingRef.model_construct(date="../../../../tmp/pwned", title="Standup")
    with pytest.raises(ValueError, match="outside the vault"):
        note_path(tmp_path, ref)


def test_note_path_allows_a_normal_date(tmp_path):
    ref = MeetingRef(date="2026-07-30", title="Standup")
    assert note_path(tmp_path, ref).is_relative_to(tmp_path)
