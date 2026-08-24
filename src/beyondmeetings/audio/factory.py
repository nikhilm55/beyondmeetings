"""Choose the capture backend for the running platform.

Backends are imported inside their branch, never at module scope: a Linux
machine must not load macOS code, and vice versa.
"""
from __future__ import annotations

import sys
from pathlib import Path

from .base import Recorder


class UnsupportedPlatformError(RuntimeError):
    """No capture backend exists for this operating system."""


def build_recorder(
    data_dir: Path,
    segment_minutes: int = 50,
    platform: str | None = None,
) -> Recorder:
    platform = platform if platform is not None else sys.platform

    if platform.startswith("linux"):
        from .pipewire import PipeWireRecorder

        return PipeWireRecorder(data_dir, segment_minutes=segment_minutes)

    if platform == "darwin":
        from .macos import MacRecorder

        return MacRecorder(data_dir, segment_minutes=segment_minutes)

    if platform == "win32":
        from .windows import WindowsRecorder

        return WindowsRecorder(data_dir, segment_minutes=segment_minutes)

    raise UnsupportedPlatformError(
        f"beyondMeetings has no capture backend for {platform}. Recording "
        "currently supports Linux, Windows and macOS."
    )
