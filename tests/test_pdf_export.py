from pathlib import Path

import pytest

from beyondmeetings.pdf_export import (
    default_pdf_export_dir,
    export_meeting_pdf,
    parse_meeting_markdown,
    reveal_pdf_for_sharing,
)


def test_default_exports_are_visible_in_downloads(tmp_path):
    assert default_pdf_export_dir(tmp_path) == tmp_path / "Downloads" / "BeyondMeetings"


def test_export_renders_markdown_as_a_real_pdf(tmp_path):
    note = tmp_path / "vault" / "Meetings" / "2026-08-17" / "Weekly.md"
    note.parent.mkdir(parents=True)
    note.write_text(
        "---\ndate: 2026-08-17\n---\n\n"
        "# Weekly\n\n## Decisions\n- **Ship** the PDF feature\n"
        "- [ ] Share the meeting\n"
    )

    target = export_meeting_pdf(
        tmp_path / "vault",
        "Meetings/2026-08-17/Weekly",
        tmp_path / "exports",
    )

    assert target == tmp_path / "exports" / "Weekly - 2026-08-17.pdf"
    assert target.read_bytes().startswith(b"%PDF")
    assert target.stat().st_size > 1_000


def test_export_can_render_a_separately_named_discussion_summary(tmp_path):
    note = tmp_path / "vault" / "Meetings" / "2026-08-18" / "Review.md"
    note.parent.mkdir(parents=True)
    note.write_text("# Review\n\n## Executive Summary\nMinutes.\n")

    target = export_meeting_pdf(
        tmp_path / "vault",
        "Meetings/2026-08-18/Review",
        tmp_path / "exports",
        markdown_override=(
            "# Review — Discussion Summary\n\n"
            "## Executive Summary\nThe discussion focused on timing.\n"
        ),
        filename_suffix="Discussion Summary - English",
        brief_label="English Discussion Summary",
        show_metrics=False,
    )

    assert target.name == "Review - 2026-08-18 - Discussion Summary - English.pdf"
    assert target.read_bytes().startswith(b"%PDF")


def test_export_refuses_a_note_outside_the_library(tmp_path):
    with pytest.raises(ValueError, match="outside"):
        export_meeting_pdf(tmp_path / "vault", "../../secret", tmp_path / "exports")


def test_ai_note_structure_drives_the_brief_layout():
    document = parse_meeting_markdown(
        "---\n"
        "tags:\n  - product\n  - planning\n"
        "date: 2026-08-17\n"
        "attendees:\n  - Nikhil\n  - Amit\n"
        "---\n\n"
        "# Product Review\n\n"
        "## Executive Summary\nWe aligned on launch.\n\n"
        "## Decisions Made\n- Ship on Friday.\n\n"
        "## Action Items\n- [ ] **Prepare release.** — **Nikhil** · Due: 2026-08-18\n",
        "Fallback",
    )

    assert document.title == "Product Review"
    assert document.metadata["tags"] == ["product", "planning"]
    assert document.metadata["attendees"] == ["Nikhil", "Amit"]
    assert document.section("Executive Summary").paragraphs == ["We aligned on launch."]
    assert len(document.section("Decisions Made").items) == 1
    assert len(document.section("Action Items").items) == 1


@pytest.mark.parametrize(
    ("platform", "expected"),
    [
        ("darwin", ["open", "-R"]),
        ("win32", ["explorer"]),
    ],
)
def test_share_reveals_the_pdf_with_the_platform_file_manager(
    tmp_path, platform, expected
):
    target = tmp_path / "Meeting.pdf"
    target.write_bytes(b"%PDF")
    calls = []

    reveal_pdf_for_sharing(
        target,
        platform=platform,
        spawn=lambda *args, **kwargs: calls.append((args, kwargs)),
    )

    assert calls[0][0][0][:len(expected)] == expected
