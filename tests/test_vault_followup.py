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


# --- Review finding #3: back-link landed in the wrong section ---

FULL_NOTE = (
    "---\ntags:\n  - meeting\ndate: 2026-07-29\n---\n\n"
    "# Prev\n\n## Executive Summary\nWe planned.\n\n"
    "## Follow-ups\n- Chase the API contract\n\n"
    "## Key Discussion Points\n- talked about scope\n\n"
    "---\n*footer*\n"
)


def _apply(tmp_path, body):
    path = tmp_path / "Prev.md"
    path.write_text(body)
    append_followup_backlink(path, MeetingRef(date="2026-07-30", title="Part 2"))
    return path.read_text()


def test_backlink_lands_under_followups_not_the_last_section(tmp_path):
    """The section ends at the next heading, not at the footer rule."""
    out = _apply(tmp_path, FULL_NOTE)
    followups = out.split("## Follow-ups\n")[1].split("## ")[0]
    assert "Followed up in:" in followups
    assert "Followed up in:" not in out.split("## Key Discussion Points\n")[1]


def test_existing_followups_content_is_preserved(tmp_path):
    out = _apply(tmp_path, FULL_NOTE)
    assert "- Chase the API contract" in out
    assert "- talked about scope" in out


def test_later_sections_stay_intact_and_ordered(tmp_path):
    out = _apply(tmp_path, FULL_NOTE)
    assert out.index("## Follow-ups") < out.index("## Key Discussion Points")
    assert out.rstrip().endswith("*footer*")


def test_a_renamed_heading_gets_a_new_section_before_the_footer(tmp_path):
    body = FULL_NOTE.replace("## Follow-ups", "## Follow-ups from last week")
    out = _apply(tmp_path, body)
    assert "## Follow-ups from last week" in out
    assert out.index("Followed up in:") < out.index("*footer*")


def test_heading_as_final_line_without_a_newline(tmp_path):
    out = _apply(tmp_path, "# Prev\n\n## Follow-ups")
    assert "## Follow-ups## Follow-ups" not in out
    assert out.count("## Follow-ups") == 1
    assert "Followed up in:" in out


def test_heading_only_inside_a_code_fence_is_ignored(tmp_path):
    body = (
        "# Prev\n\n## Notes\n\n```markdown\n## Follow-ups\n- example\n```\n\n"
        "---\n*footer*\n"
    )
    out = _apply(tmp_path, body)
    fenced = out.split("```markdown\n")[1].split("```")[0]
    assert "Followed up in:" not in fenced
    assert "Followed up in:" in out


def test_still_idempotent_with_the_new_placement(tmp_path):
    path = tmp_path / "Prev.md"
    path.write_text(FULL_NOTE)
    ref = MeetingRef(date="2026-07-30", title="Part 2")
    append_followup_backlink(path, ref)
    append_followup_backlink(path, ref)
    assert path.read_text().count("Followed up in:") == 1
