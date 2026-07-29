"""Obsidian detection and flatpak installation."""
from __future__ import annotations

import shutil
import subprocess

from .base import Check, CheckResult

FLATPAK_ID = "md.obsidian.Obsidian"


def _flatpak_list() -> str:
    if not shutil.which("flatpak"):
        return ""
    return subprocess.run(
        ["flatpak", "list", "--app", "--columns=application"],
        capture_output=True, text=True, check=False,
    ).stdout


class ObsidianCheck(Check):
    id = "obsidian"
    label = "Obsidian"
    description = "Where your meeting notes and task board live."
    required = True

    def detect(self) -> CheckResult:
        binary = shutil.which("obsidian")
        if binary:
            return CheckResult(status="ok", detail=binary)
        if FLATPAK_ID in _flatpak_list():
            return CheckResult(status="ok", detail=f"flatpak: {FLATPAK_ID}")

        if shutil.which("flatpak"):
            detail = (
                "Not installed. beyondMeetings can install it from Flathub, "
                "or download it yourself from obsidian.md."
            )
        else:
            detail = (
                "Not installed, and flatpak is unavailable for automatic install. "
                "Download Obsidian from obsidian.md and install the .deb or AppImage."
            )
        return CheckResult(status="missing", detail=detail)

    @property
    def fixable(self) -> bool:
        return bool(shutil.which("flatpak"))

    def fix(self, **kwargs) -> CheckResult:
        proc = subprocess.run(
            ["flatpak", "install", "-y", "--noninteractive", "flathub", FLATPAK_ID],
            capture_output=True, text=True, check=False,
        )
        if proc.returncode != 0:
            return CheckResult(
                status="missing",
                detail=f"Flatpak install failed: {proc.stderr[:300]}",
            )
        return self.detect()
