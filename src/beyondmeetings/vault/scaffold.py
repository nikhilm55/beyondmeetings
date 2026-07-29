"""Create the vault structure. Never overwrites existing content."""
from __future__ import annotations

from datetime import date
from pathlib import Path

TASK_BOARD_TEMPLATE = """---
tags: [tasks]
updated: {today}
---

# Task Board

← [[Home]]

---

> [!abstract] Board at a Glance
> `0 pending` · `0 in discussion` · `0 blocked` · `0 done`

---

> [!danger]+ Blocked — 0
> No blocked tasks right now.

> [!todo]+ Pending — 0

> [!success]- Done — 0
"""

HOME_TEMPLATE = """---
tags: [home, dashboard]
updated: {today}
---

# Workspace

---

## Tasks

> [!abstract] Board at a Glance
> `0 pending` · `0 in discussion` · `0 blocked` · `0 done`

> [!danger]+ Blocked — 0
> No blocked tasks right now.

> [!todo]+ Pending — 0
>
> → [[Tasks/Task Board|See all tasks]]

→ [[Tasks/Task Board|Full task board]]

---

## Meetings

> [!example]+ Recent
"""


def scaffold_vault(vault: Path) -> None:
    today = date.today().isoformat()
    (vault / "Meetings").mkdir(parents=True, exist_ok=True)
    (vault / "Tasks").mkdir(parents=True, exist_ok=True)

    board = vault / "Tasks" / "Task Board.md"
    if not board.exists():
        board.write_text(TASK_BOARD_TEMPLATE.format(today=today))

    home = vault / "Home.md"
    if not home.exists():
        home.write_text(HOME_TEMPLATE.format(today=today))
