"""Windows WASAPI capture prerequisite."""
from __future__ import annotations

import importlib.util

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
