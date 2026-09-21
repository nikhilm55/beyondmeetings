"""Finding the external binaries the pipeline shells out to.

PATH answers this on every platform, and on Linux and macOS it is the whole
answer: ffmpeg comes from apt or brew and lands somewhere already on PATH.

Windows is the exception. A bare Windows machine has no package manager we can
rely on and no ffmpeg, so the installer fetches one itself and drops it in the
application's own bin directory — deliberately *not* by rewriting the user's
PATH, which is a registry edit an installer should not be making behind their
back. That directory therefore has to be searched explicitly, which is what
this module is for.

`app_bin_dirs()` returns an empty list off Windows, so `which_tool` is exactly
`shutil.which` there and no Linux behaviour changes.
"""
from __future__ import annotations

import os
import shutil
import sys
from pathlib import Path

# Matches $BinDir in install.ps1 and uninstall.ps1. Note the capital M: the
# program lives under beyondMeetings\ while recordings live under the
# all-lowercase beyondmeetings\, so an uninstall cannot take meetings with it.
APP_DIR_NAME = "beyondMeetings"


def app_bin_dirs(platform: str | None = None) -> list[Path]:
    """Directories the installer may have put a helper binary in, in order."""
    platform = platform if platform is not None else sys.platform
    if platform != "win32":
        return []

    found: list[Path] = []
    override = os.environ.get("BEYONDMEETINGS_BIN")
    if override:
        found.append(Path(override))
    local = os.environ.get("LOCALAPPDATA")
    if local:
        found.append(Path(local) / APP_DIR_NAME / "bin")
    # The venv's Scripts\ directory: where a pip-installed console script goes,
    # and the one location that is right even when the environment variables
    # above are missing or point somewhere else.
    found.append(Path(sys.executable).parent)

    unique: list[Path] = []
    for folder in found:
        if folder not in unique:
            unique.append(folder)
    return unique


def which_tool(name: str, platform: str | None = None) -> str | None:
    """`shutil.which`, plus the application's own bin directory on Windows."""
    on_path = shutil.which(name)
    if on_path:
        return on_path

    platform = platform if platform is not None else sys.platform
    if platform != "win32":
        return None

    for folder in app_bin_dirs(platform):
        candidate = folder / f"{name}.exe"
        if candidate.is_file():
            return str(candidate)
    return None
