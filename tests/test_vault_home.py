import pytest

from beyondmeetings.models import MeetingRef
from beyondmeetings.vault.home import add_recent_meeting, sync_counters, touch_updated

HOME = """---
tags: [home, dashboard]
updated: 2026-07-01
---

# Workspace

## Tasks

> [!abstract] Board at a Glance
> `2 pending` · `0 in discussion` · `0 blocked` · `1 done`

> [!todo]+ Pending — 2
>
> → [[Tasks/Task Board|See all tasks]]

## Meetings

> [!example]+ Recent
> **[[Meetings/2026-07-01/Old|Old Meeting]]** · Zenith · Something older
"""

REF = MeetingRef(date="2026-07-30", title="Phase 4 - Plan")


def test_new_meeting_is_prepended_above_older_ones():
    out = add_recent_meeting(HOME, REF, "Phase 4 — Plan", "Acme",
                             "Licences approved")
    body = out.split("> [!example]+ Recent\n", 1)[1]
    assert body.splitlines()[0].startswith(
        "> **[[Meetings/2026-07-30/Phase 4 - Plan|Phase 4 — Plan]]**"
    )
    assert "Old Meeting" in out


def test_entry_contains_project_and_description():
    out = add_recent_meeting(HOME, REF, "Phase 4 — Plan", "Acme",
                             "Licences approved")
    assert "· Acme · Licences approved" in out


def test_follow_up_marker_is_appended_when_linked():
    prev = MeetingRef(date="2026-07-29", title="Design QA Review")
    out = add_recent_meeting(HOME, REF, "Phase 4 — Plan", "Acme",
                             "Licences approved", previous=prev,
                             previous_display="Design QA Review")
    assert ("· ↳ follow-up to [[Meetings/2026-07-29/Design QA Review]]"
            in out)


def test_no_follow_up_marker_when_standalone():
    out = add_recent_meeting(HOME, REF, "Phase 4 — Plan", "Acme", "x")
    assert "follow-up to" not in out


def test_project_omitted_cleanly_when_unknown():
    out = add_recent_meeting(HOME, REF, "Phase 4 — Plan", None, "Licences approved")
    assert "**[[Meetings/2026-07-30/Phase 4 - Plan|Phase 4 — Plan]]** · Licences" in out


def test_sync_counters_matches_task_board():
    out = sync_counters(HOME, pending=7)
    assert "`7 pending`" in out
    assert "> [!todo]+ Pending — 7" in out


def test_touch_updated_rewrites_frontmatter_date():
    out = touch_updated(HOME, "2026-07-30")
    assert "updated: 2026-07-30" in out
    assert "updated: 2026-07-01" not in out


def test_missing_recent_callout_raises():
    with pytest.raises(ValueError):
        add_recent_meeting("# Home\n", REF, "T", "P", "d")


def test_first_meeting_into_an_empty_recent_callout(tmp_path):
    """Regression: the scaffolded Recent callout is the final line."""
    from beyondmeetings.vault.scaffold import scaffold_vault

    scaffold_vault(tmp_path)
    text = (tmp_path / "Home.md").read_text()
    out = add_recent_meeting(text, REF, "Phase 4 — Plan", "Acme", "First one")
    assert "> [!example]+ Recent\n> **[[Meetings/2026-07-30/Phase 4 - Plan" in out


def test_sync_counters_preserves_the_blank_line_after_the_header(tmp_path):
    from beyondmeetings.vault.scaffold import scaffold_vault

    scaffold_vault(tmp_path)
    text = (tmp_path / "Home.md").read_text()
    out = sync_counters(text, pending=3)
    assert "> [!todo]+ Pending — 3\n>\n> → [[Tasks/Task Board|See all tasks]]" in out
