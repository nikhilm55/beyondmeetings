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


# --- Review finding #7: the schema-echo case picked the wrong block ---

def test_prefers_a_real_note_over_an_echoed_schema():
    """Some models restate the schema in one fence and answer in the next."""
    raw = (
        "Here is the schema I used:\n"
        '```json\n{"title": "string", "date": "YYYY-MM-DD"}\n```\n'
        "And the note:\n"
        f"```json\n{VALID}\n```\n"
    )
    assert parse_meeting_note(raw).title == "Standup"


def test_falls_through_to_the_bare_text_when_no_fence_parses():
    assert parse_meeting_note(f"```\nnot json at all\n```\n{VALID}").title == "Standup"


def test_uppercase_fence_language_is_handled():
    assert parse_meeting_note(f"```JSON\n{VALID}\n```").title == "Standup"


def test_error_message_does_not_claim_to_repair():
    with pytest.raises(ResponseParseError, match="could not read a meeting note"):
        parse_meeting_note('{"title": "no summary or date"}')
