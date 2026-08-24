"""Checks for the binaries the audio pipeline shells out to."""
from __future__ import annotations

import shutil
import subprocess

from .base import Check, CheckResult

MANAGERS = [
    ("apt-get", "sudo apt-get install -y {pkg}"),
    ("dnf", "sudo dnf install -y {pkg}"),
    ("pacman", "sudo pacman -S --noconfirm {pkg}"),
    ("zypper", "sudo zypper install -y {pkg}"),
]


def install_hint(package: str) -> str:
    for binary, template in MANAGERS:
        if shutil.which(binary):
            return template.format(pkg=package)
    return f"Install {package} with your system package manager."


class PipeWireCheck(Check):
    id = "pipewire"
    label = "PipeWire audio"
    description = "Captures every participant by mixing all audio sources."
    required = True

    def detect(self) -> CheckResult:
        pactl = shutil.which("pactl")
        capture = next(
            (binary for binary in ("parec", "pw-record") if shutil.which(binary)),
            None,
        )
        if not pactl or not capture:
            missing = []
            if not pactl:
                missing.append("pactl")
            if not capture:
                missing.append("parec or pw-record")
            return CheckResult(
                status="missing",
                detail=(
                    f"Not found: {', '.join(missing)}. beyondMeetings needs the "
                    "pactl plus either parec or pw-record for Linux desktop "
                    "audio capture, including PipeWire."
                ),
            )
        return CheckResult(status="ok", detail=f"pactl and {capture} found")


class FfmpegCheck(Check):
    id = "ffmpeg"
    label = "ffmpeg"
    description = "Compresses recordings before upload."
    required = True

    def detect(self) -> CheckResult:
        found = shutil.which("ffmpeg")
        if not found:
            return CheckResult(status="missing", detail=install_hint("ffmpeg"))
        return CheckResult(status="ok", detail=found)

    @property
    def fixable(self) -> bool:
        return True

    def fix(self, **kwargs) -> CheckResult:
        command = install_hint("ffmpeg")
        if not command.startswith("sudo"):
            return CheckResult(status="missing", detail=command)
        proc = subprocess.run(command.split(), capture_output=True, text=True)
        if proc.returncode != 0:
            return CheckResult(
                status="missing",
                detail=f"Install failed. Run manually: {command}",
            )
        return self.detect()
