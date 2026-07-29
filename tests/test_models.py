import pytest
from pydantic import ValidationError

from beyondmeetings.models import ActionItem, MeetingNote, MeetingRef


def test_meeting_note_minimal_defaults():
    note = MeetingNote(title="Standup", date="2026-07-30", executive_summary="Short.")
    assert note.tags == []
    assert note.action_items == []
    assert note.is_informal is False
    assert note.follow_up_of is None


def test_action_item_priority_defaults_to_medium():
    item = ActionItem(task="Ship it")
    assert item.priority == "MEDIUM"
    assert item.owner is None


def test_action_item_rejects_unknown_priority():
    with pytest.raises(ValidationError):
        ActionItem(task="Ship it", priority="URGENT")


def test_meeting_ref_round_trips_through_id():
    ref = MeetingRef(date="2026-07-29", title="Design QA Review")
    assert ref.id == "2026-07-29/Design QA Review"
    assert MeetingRef.from_id(ref.id) == ref


def test_meeting_ref_from_id_rejects_malformed():
    with pytest.raises(ValueError):
        MeetingRef.from_id("no-slash-here")
