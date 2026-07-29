from datetime import date, timedelta

from beyondmeetings.models import MeetingRef
from beyondmeetings.vault.followup import (
    append_followup_backlink,
    gather_candidates,
)


def _write(vault, day, title, summary="A summary.", tags="  - Acme"):
    folder = vault / "Meetings" / day
    folder.mkdir(parents=True, exist_ok=True)
    (folder / f"{title}.md").write_text(
        f"---\ntags:\n  - meeting\n{tags}\ndate: {day}\n---\n\n"
        f"# {title}\n\n## Executive Summary\n{summary}\n\n## Decisions Made\n- x\n"
    )


def test_gathers_notes_within_the_window(tmp_path):
    recent = (date.today() - timedelta(days=3)).isoformat()
    _write(tmp_path, recent, "Recent Meeting")
    found = gather_candidates(tmp_path, days=30)
    assert [c.ref.id for c in found] == [f"{recent}/Recent Meeting"]


def test_ignores_notes_outside_the_window(tmp_path):
    old = (date.today() - timedelta(days=90)).isoformat()
    _write(tmp_path, old, "Ancient Meeting")
    assert gather_candidates(tmp_path, days=30) == []


def test_extracts_executive_summary_and_tags(tmp_path):
    day = (date.today() - timedelta(days=1)).isoformat()
    _write(tmp_path, day, "Yesterday", summary="We agreed the plan.")
    candidate = gather_candidates(tmp_path, days=30)[0]
    assert candidate.executive_summary == "We agreed the plan."
    assert "Acme" in candidate.tags


def test_results_are_newest_first(tmp_path):
    for offset in (1, 5, 3):
        day = (date.today() - timedelta(days=offset)).isoformat()
        _write(tmp_path, day, f"Meeting {offset}")
    dates = [c.ref.date for c in gather_candidates(tmp_path, days=30)]
    assert dates == sorted(dates, reverse=True)


def test_respects_the_limit(tmp_path):
    for offset in range(1, 12):
        day = (date.today() - timedelta(days=offset)).isoformat()
        _write(tmp_path, day, f"Meeting {offset}")
    assert len(gather_candidates(tmp_path, days=30, limit=5)) == 5


def test_missing_meetings_dir_returns_empty(tmp_path):
    assert gather_candidates(tmp_path, days=30) == []


def test_backlink_appends_to_existing_followups_section(tmp_path):
    _write(tmp_path, "2026-07-29", "Prev")
    path = tmp_path / "Meetings" / "2026-07-29" / "Prev.md"
    path.write_text(path.read_text() + "\n## Follow-ups\n- Something earlier.\n\n---\n")
    append_followup_backlink(
        path, MeetingRef(date="2026-07-30", title="Next Meeting")
    )
    text = path.read_text()
    assert "- Something earlier." in text
    assert "- Followed up in: [[Meetings/2026-07-30/Next Meeting]]" in text


def test_backlink_creates_followups_section_when_absent(tmp_path):
    _write(tmp_path, "2026-07-29", "Prev")
    path = tmp_path / "Meetings" / "2026-07-29" / "Prev.md"
    append_followup_backlink(
        path, MeetingRef(date="2026-07-30", title="Next Meeting")
    )
    text = path.read_text()
    assert "## Follow-ups" in text
    assert "- Followed up in: [[Meetings/2026-07-30/Next Meeting]]" in text


def test_backlink_never_lands_inside_the_frontmatter(tmp_path):
    """Regression: rpartition('\\n---') used to match the frontmatter fence."""
    _write(tmp_path, "2026-07-29", "Prev")
    path = tmp_path / "Meetings" / "2026-07-29" / "Prev.md"
    append_followup_backlink(
        path, MeetingRef(date="2026-07-30", title="Next Meeting")
    )
    text = path.read_text()
    _, _, after_frontmatter = text.partition("---\n")
    front, sep, body = after_frontmatter.partition("\n---")
    assert sep, "frontmatter fence must still be intact"
    assert "Follow-ups" not in front
    assert "Follow-ups" in body


def test_backlink_preserves_the_frontmatter_verbatim(tmp_path):
    _write(tmp_path, "2026-07-29", "Prev")
    path = tmp_path / "Meetings" / "2026-07-29" / "Prev.md"
    original_front = path.read_text().split("\n---", 1)[0]
    append_followup_backlink(
        path, MeetingRef(date="2026-07-30", title="Next Meeting")
    )
    assert path.read_text().split("\n---", 1)[0] == original_front


def test_backlink_keeps_body_content_intact(tmp_path):
    _write(tmp_path, "2026-07-29", "Prev", summary="A summary.")
    path = tmp_path / "Meetings" / "2026-07-29" / "Prev.md"
    append_followup_backlink(
        path, MeetingRef(date="2026-07-30", title="Next Meeting")
    )
    text = path.read_text()
    assert "# Prev" in text
    assert "## Executive Summary\nA summary." in text
    assert "## Decisions Made\n- x" in text


def test_backlink_is_not_duplicated_on_repeat(tmp_path):
    _write(tmp_path, "2026-07-29", "Prev")
    path = tmp_path / "Meetings" / "2026-07-29" / "Prev.md"
    ref = MeetingRef(date="2026-07-30", title="Next Meeting")
    append_followup_backlink(path, ref)
    append_followup_backlink(path, ref)
    assert path.read_text().count("Followed up in:") == 1
