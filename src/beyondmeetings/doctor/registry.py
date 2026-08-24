"""The ordered list of prerequisite checks.

Platform-specific rows are chosen here and nowhere else. macOS checks are
imported inside their branch, so a Linux machine never loads them.
"""
from __future__ import annotations

import sys
from pathlib import Path

from ..config import DEFAULT_CONFIG_PATH, Config
from .autostart import AutostartCheck
from .base import Check
from .choices import ProviderChoice, TranscriberChoice
from .desktop import DesktopLauncherCheck
from .keys import GroqKeyCheck, ProviderKeyCheck
from .mcp import McpCheck
from .rules_check import RulesCheck
from .system import FfmpegCheck, PipeWireCheck
from .transcriber import WhisperModelCheck
from .vault import StorageCheck


def build_checks(
    config: Config,
    config_path: Path | None = None,
    secret_dir: Path | None = None,
    platform: str | None = None,
) -> list[Check]:
    config_path = Path(config_path or DEFAULT_CONFIG_PATH)
    platform = platform if platform is not None else sys.platform
    macos = platform == "darwin"
    windows = platform == "win32"

    checks: list[Check] = [
        # Choices first — they change what the rows below mean.
        ProviderChoice(config, config_path=config_path),
        TranscriberChoice(config, config_path=config_path),
    ]

    if macos:
        from .macos import (
            AppBundleCheck,
            CaptureHelperCheck,
            MicrophonePermissionCheck,
            ScreenRecordingPermissionCheck,
            XcodeToolsCheck,
        )

        checks += [
            XcodeToolsCheck(),
            AppBundleCheck(),
            CaptureHelperCheck(),
            ScreenRecordingPermissionCheck(),
            MicrophonePermissionCheck(),
        ]
    elif windows:
        from .windows import WindowsAudioCheck

        checks.append(WindowsAudioCheck())
    else:
        checks.append(PipeWireCheck())

    checks.append(FfmpegCheck())

    # The Groq key is only a prerequisite when Groq is doing the transcribing.
    if config.transcriber == "groq":
        checks.append(GroqKeyCheck(secret_dir=secret_dir))

    checks += [
        ProviderKeyCheck(
            provider=config.provider,
            secret_dir=secret_dir,
            ollama_host=config.ollama_host,
            model=config.model,
            agent_command=config.agent_command or None,
        ),
        WhisperModelCheck(config),
        StorageCheck(config, config_path=config_path),
        RulesCheck(config),
        McpCheck(config),
    ]

    # Both are freedesktop-specific: a .desktop entry and an XDG autostart
    # file mean nothing on macOS, where the .app bundle covers the same ground.
    if not macos and not windows:
        checks += [DesktopLauncherCheck(config), AutostartCheck(config)]

    return checks
