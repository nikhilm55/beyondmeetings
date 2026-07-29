import pytest

from beyondmeetings.models import ActionItem, MeetingRef
from beyondmeetings.vault.taskboard import add_tasks, count_pending, update_counters

BOARD = """---
tags: [tasks]
updated: 2026-07-01
---

# Task Board

> [!abstract] Board at a Glance
> `2 pending` · `0 in discussion` · `0 blocked` · `1 done`

> [!todo]+ Pending — 2
> > **==Existing One==** · `Zenith` · `LOW`
> > Already here. — **Sam** · [[Meetings/2026-07-01/Old]]
> >
> > **==Existing Two==** · `LOW`
> > Also here. · [[Meetings/2026-07-01/Old]]
> >

> [!success]- Done — 1
"""

REF = MeetingRef(date="2026-07-30", title="Phase 4 - Plan")


def test_count_pending_reads_the_header():
    assert count_pending(BOARD) == 2


def test_add_tasks_prepends_new_entries_after_header():
    out = add_tasks(BOARD, [ActionItem(task="Procure licences", owner="Sam",
                                       project="Acme", priority="HIGH",
                                       due="2026-08-01")], REF, "Buy two licences.")
    body = out.split("> [!todo]+ Pending — 3\n", 1)[1]
    assert body.startswith("> > **==Procure licences==** · `Acme` · `HIGH`\n")


def test_added_task_line_has_owner_due_and_meeting_link():
    out = add_tasks(BOARD, [ActionItem(task="Procure licences", owner="Sam",
                                       project="Acme", priority="HIGH",
                                       due="2026-08-01")], REF, "Buy two licences.")
    assert ("> > Buy two licences. — **Sam** · Due: 2026-08-01 · "
            "[[Meetings/2026-07-30/Phase 4 - Plan]]\n") in out


def test_project_omitted_when_absent():
    out = add_tasks(BOARD, [ActionItem(task="No project", priority="LOW")],
                    REF, "Do it.")
    assert "> > **==No project==** · `LOW`\n" in out


def test_counters_increase_by_number_of_tasks():
    out = add_tasks(BOARD, [ActionItem(task="A"), ActionItem(task="B")], REF, "d")
    assert "> [!todo]+ Pending — 4" in out
    assert "`4 pending`" in out


def test_existing_tasks_are_preserved():
    out = add_tasks(BOARD, [ActionItem(task="A")], REF, "d")
    assert "**==Existing One==**" in out
    assert "**==Existing Two==**" in out


def test_adding_empty_list_is_a_no_op():
    assert add_tasks(BOARD, [], REF, "d") == BOARD


def test_update_counters_rewrites_both_places():
    out = update_counters(BOARD, pending=99)
    assert "`99 pending`" in out
    assert "> [!todo]+ Pending — 99" in out
    assert "`1 done`" in out


def test_add_tasks_raises_when_pending_callout_missing():
    with pytest.raises(ValueError):
        add_tasks("# Empty board\n", [ActionItem(task="A")], REF, "d")
