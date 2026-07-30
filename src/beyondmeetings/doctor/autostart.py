"""Launch beyondMeetings at login via a freedesktop autostart entry."""
from __future__ import annotations

from pathlib import Path

from ..config import Config
from .base import Check, CheckResult

ENTRY = """[Desktop Entry]
Type=Application
Name=beyondMeetings (background)
Comment=Keeps beyondMeetings ready so the app icon opens instantly
Exec=beyondmeetings serve --no-browser --no-tray
Terminal=false
X-GNOME-Autostart-enabled=true
"""


class AutostartCheck(Check):
    id = "autostart"
    label = "Start at login"
    description = "Runs beyondMeetings in the background when you log in."
    required = False

    def __init__(self, config: Config, home: Path | None = None):
        self.config = config
        self.home = Path(home or Path.home())

    @property
    def _entry_path(self) -> Path:
        return self.home / ".config" / "autostart" / "beyondmeetings.desktop"

    def detect(self) -> CheckResult:
        if self._entry_path.is_file():
            return CheckResult(status="ok", detail=str(self._entry_path))
        return CheckResult(status="missing", detail="Not set up.")

    @property
    def fixable(self) -> bool:
        return True

    def fix(self, **kwargs) -> CheckResult:
        self._entry_path.parent.mkdir(parents=True, exist_ok=True)
        self._entry_path.write_text(ENTRY, encoding="utf-8")
        return self.detect()
