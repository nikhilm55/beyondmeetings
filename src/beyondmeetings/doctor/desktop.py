"""The app icon in the desktop's application grid."""
from __future__ import annotations

from pathlib import Path

from ..config import Config
from ..desktop import desktop_entry_path, icon_install_path, install_desktop_entry
from .base import Check, CheckResult


class DesktopLauncherCheck(Check):
    id = "launcher"
    label = "App icon"
    description = (
        "Adds beyondMeetings to your applications. Clicking it opens the app, "
        "starting the server only if it is not already running."
    )
    required = False

    def __init__(self, config: Config, home: Path | None = None):
        self.config = config
        self.home = Path(home) if home else None

    def detect(self) -> CheckResult:
        entry = desktop_entry_path(self.home)
        icon = icon_install_path(self.home)
        if entry.is_file() and icon.is_file():
            return CheckResult(status="ok", detail=str(entry))
        missing = "icon" if entry.is_file() else "launcher"
        return CheckResult(status="missing", detail=f"No {missing} installed yet.")

    @property
    def fixable(self) -> bool:
        return True

    def fix(self, **kwargs) -> CheckResult:
        install_desktop_entry(self.home)
        return self.detect()
