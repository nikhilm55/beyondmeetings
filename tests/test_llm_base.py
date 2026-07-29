import pytest

from beyondmeetings.llm.base import ResponseParseError, parse_meeting_note

VALID = """
{"title": "Standup", "date": "2026-07-30",
 "executive_summary": "We synced.", "is_informal": false}
"""


def test_parses_bare_json():
    note = parse_meeting_note(VALID)
    assert note.title == "Standup"


def test_parses_json_in_markdown_fence():
    note = parse_meeting_note(f"```json\n{VALID}\n```")
    assert note.title == "Standup"


def test_parses_json_surrounded_by_prose():
    note = parse_meeting_note(f"Here is the note:\n{VALID}\nHope that helps!")
    assert note.title == "Standup"


def test_rejects_follow_up_of_not_in_candidates():
    raw = VALID.replace('"is_informal": false', '"is_informal": false, '
                        '"follow_up_of": "2026-01-01/Invented Meeting"')
    note = parse_meeting_note(raw, valid_candidate_ids=["2026-07-29/Real Meeting"])
    assert note.follow_up_of is None


def test_keeps_follow_up_of_when_in_candidates():
    raw = VALID.replace('"is_informal": false', '"is_informal": false, '
                        '"follow_up_of": "2026-07-29/Real Meeting"')
    note = parse_meeting_note(raw, valid_candidate_ids=["2026-07-29/Real Meeting"])
    assert note.follow_up_of == "2026-07-29/Real Meeting"


def test_raises_when_no_json_present():
    with pytest.raises(ResponseParseError):
        parse_meeting_note("I could not analyse that transcript.")


def test_raises_when_required_field_missing():
    with pytest.raises(ResponseParseError):
        parse_meeting_note('{"title": "No summary or date"}')
