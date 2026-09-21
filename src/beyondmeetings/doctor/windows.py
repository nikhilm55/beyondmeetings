"""Windows prerequisites: WASAPI capture, Start Menu entry, login startup.

The launcher and autostart rows reuse the ids the freedesktop checks use
(`launcher`, `autostart`) so the wizard and `doctor` render the same rows on
every platform — only what sits behind them differs.
"""
from __future__ import annotations

import importlib.util
from pathlib import Path

from ..desktop_windows import (
    install_shortcut,
    install_startup_shortcut,
    shortcut_path,
    startup_shortcut_path,
)
from ..provision_windows import ensure_webview2, registry_version
from .base import Check, CheckResult


class WindowsAudioCheck(Check):
    id = "windows_audio"
    label = "Windows audio capture"
    description = "WASAPI loopback records call audio together with your microphone."
    required = True

    def detect(self) -> CheckResult:
        if importlib.util.find_spec("soundcard") is None:
            return CheckResult(
                status="missing",
                detail="SoundCard is missing; reinstall the Windows application.",
            )
        return CheckResult(status="ok", detail="WASAPI capture is available.")


class WebView2Check(Check):
    """The runtime pywebview draws the desktop window in.

    Windows 11 ships it; a freshly installed Windows 10 often does not, and
    without it the app window fails to open. Not `required`, because the same
    UI is reachable in a browser at 127.0.0.1:7788 — but a user who installed
    a desktop app wants a desktop window, so doctor offers to fetch it.
    """

    id = "webview2"
    label = "App window runtime"
    description = "Microsoft Edge WebView2 draws the beyondMeetings window."
    required = False

    def detect(self) -> CheckResult:
        version = registry_version()
        if version:
            return CheckResult(status="ok", detail=f"WebView2 {version}")
        return CheckResult(
            status="missing",
            detail=(
                "Not installed. The app window will not open, though the same "
                "page works in a browser at http://127.0.0.1:7788."
            ),
        )

    @property
    def fixable(self) -> bool:
        return True

    def fix(self, **kwargs) -> CheckResult:
        outcome = ensure_webview2()
        if not outcome.satisfied:
            return CheckResult(status="missing", detail=outcome.detail)
        return self.detect()


class StartMenuShortcutCheck(Check):
    id = "launcher"
    label = "App icon"
    description = "Puts beyondMeetings in the Start Menu so it opens like an app."
    required = False

    def __init__(self, home: Path | None = None):
        self.home = Path(home) if home else None

    def detect(self) -> CheckResult:
        link = shortcut_path(self.home)
        if link.is_file():
            return CheckResult(status="ok", detail=str(link))
        return CheckResult(status="missing", detail=f"No shortcut at {link}.")

    @property
    def fixable(self) -> bool:
        return True

    def fix(self, **kwargs) -> CheckResult:
        install_shortcut(home=self.home)
        return self.detect()


class WindowsAutostartCheck(Check):
    id = "autostart"
    label = "Start at login"
    description = (
        "Runs beyondMeetings in the background at login and shows recording "
        "status in the notification area."
    )
    required = False

    def __init__(self, home: Path | None = None):
        self.home = Path(home) if home else None

    def detect(self) -> CheckResult:
        link = startup_shortcut_path(self.home)
        if link.is_file():
            return CheckResult(status="ok", detail=str(link))
        return CheckResult(status="missing", detail="Not set up.")

    @property
    def fixable(self) -> bool:
        return True

    def fix(self, **kwargs) -> CheckResult:
        install_startup_shortcut(home=self.home)
        return self.detect()
