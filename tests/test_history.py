from datetime import date

from beyondmeetings.history import list_meetings, search_meetings


def _note(vault, day, title, summary="A summary.", tag="Acme"):
    folder = vault / "Meetings" / day
    folder.mkdir(parents=True, exist_ok=True)
    (folder / f"{title}.md").write_text(
        f"---\ntags:\n  - meeting\n  - {tag}\ndate: {day}\n---\n\n"
        f"# {title}\n\n## Executive Summary\n{summary}\n\n"
        f"## Action Items\n- [ ] **One** — **Sam**\n- [ ] **Two**\n"
    )


def test_empty_vault_returns_nothing(tmp_path):
    assert list_meetings(tmp_path) == []


def test_lists_a_meeting_with_its_metadata(tmp_path):
    _note(tmp_path, "2026-07-30", "Standup", summary="We synced.")
    row = list_meetings(tmp_path)[0]
    assert row["title"] == "Standup"
    assert row["date"] == "2026-07-30"
    assert row["summary"] == "We synced."
    assert row["project"] == "Acme"
    assert row["link"] == "Meetings/2026-07-30/Standup"
    assert row["recorded_at"] == ""


def test_reads_the_recording_time_when_available(tmp_path):
    _note(tmp_path, "2026-07-30", "Standup")
    path = tmp_path / "Meetings" / "2026-07-30" / "Standup.md"
    path.write_text(path.read_text().replace(
        "date: 2026-07-30", "date: 2026-07-30\nrecorded_at: 2026-07-30T14:30:00"
    ))
    assert list_meetings(tmp_path)[0]["recorded_at"] == "2026-07-30T14:30:00"


def test_counts_action_items(tmp_path):
    _note(tmp_path, "2026-07-30", "Standup")
    assert list_meetings(tmp_path)[0]["tasks"] == 2


def test_newest_first(tmp_path):
    for day in ("2026-07-28", "2026-07-30", "2026-07-29"):
        _note(tmp_path, day, f"Meeting {day}")
    dates = [m["date"] for m in list_meetings(tmp_path)]
    assert dates == sorted(dates, reverse=True)


def test_respects_the_limit(tmp_path):
    for i in range(1, 8):
        _note(tmp_path, f"2026-07-0{i}", f"Meeting {i}")
    assert len(list_meetings(tmp_path, limit=3)) == 3


def test_ignores_non_date_folders(tmp_path):
    (tmp_path / "Meetings" / "Templates").mkdir(parents=True)
    (tmp_path / "Meetings" / "Templates" / "Blank.md").write_text("# Blank")
    assert list_meetings(tmp_path) == []


def test_handles_a_note_with_no_summary(tmp_path):
    folder = tmp_path / "Meetings" / "2026-07-30"
    folder.mkdir(parents=True)
    (folder / "Bare.md").write_text("# Bare\n")
    row = list_meetings(tmp_path)[0]
    assert row["title"] == "Bare"
    assert row["summary"] == ""


def test_marks_informal_meetings_with_no_tasks(tmp_path):
    folder = tmp_path / "Meetings" / "2026-07-30"
    folder.mkdir(parents=True)
    (folder / "Catch-up.md").write_text(
        "---\ntags:\n  - meeting\ndate: 2026-07-30\n---\n\n"
        "# Catch-up\n\n## Action Items\nNone recorded.\n"
    )
    assert list_meetings(tmp_path)[0]["tasks"] == 0


def test_missing_meetings_directory_is_not_an_error(tmp_path):
    assert list_meetings(tmp_path / "nope") == []


def test_reads_real_titles_with_punctuation(tmp_path):
    _note(tmp_path, "2026-07-30", "Phase 4 - Resourcing & Tooling")
    assert list_meetings(tmp_path)[0]["title"] == "Phase 4 - Resourcing & Tooling"


def test_library_search_finds_content_and_returns_clickable_sources(tmp_path):
    _note(tmp_path, "2026-07-30", "Delivery plan", summary="Mumbai rollout")
    result = search_meetings(tmp_path, "What did we say about Mumbai?")
    assert "one relevant meeting" in result["answer"]
    assert result["sources"][0]["title"] == "Delivery plan"
    assert result["sources"][0]["link"].startswith("Meetings/")


def test_library_search_understands_today(tmp_path):
    _note(tmp_path, "2026-08-11", "Daily review")
    result = search_meetings(
        tmp_path, "show meetings from today", today=date(2026, 8, 11)
    )
    assert result["sources"][0]["date"] == "2026-08-11"


def test_library_search_does_not_return_unrelated_notes(tmp_path):
    _note(tmp_path, "2026-07-30", "Budget")
    assert search_meetings(tmp_path, "quantum banana")["sources"] == []
