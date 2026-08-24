"""Allow `python -m beyondmeetings`.

The Windows login shortcut points at `pythonw.exe -m beyondmeetings serve
--no-browser`: pythonw has no console, so the tray starts at login without
flashing a black window. The console script cannot be used for that, and
pythonw needs a module to run rather than an entry-point exe.
"""
from __future__ import annotations

from .cli import main

if __name__ == "__main__":
    raise SystemExit(main())
