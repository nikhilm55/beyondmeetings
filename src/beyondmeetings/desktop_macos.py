"""The macOS .app bundle.

Deliberately a separate module rather than a restructuring of desktop.py: the
Linux launcher is working code and macOS has no business rearranging it. The
two share nothing but `resolve_executable` and a display name.

The bundle is not cosmetic. macOS keys TCC privacy grants per bundle
identifier, so a pip-installed CLI has no identity of its own — grants attach
to the launching terminal and do not carry over to an app icon. The bundle is
what gives the capture a stable identity, which is also why `bmcapture` is
copied inside it rather than left on PATH.
"""
from __future__ import annotations

import plistlib
import shutil
import stat
from pathlib import Path

from .desktop import resolve_executable

APP_NAME = "beyondMeetings"
BUNDLE_ID = "com.beyondmeetings.app"
HELPER_NAME = "bmcapture"
MINIMUM_MACOS = "13.0"

MICROPHONE_REASON = (
    "beyondMeetings records your microphone so your own voice appears in the "
    "meeting transcript."
)

# `exec` so the app's process is the server rather than a shell that owns it —
# macOS attributes privacy grants through the process tree, and an extra shell
# in the middle is one more thing that can confuse that.
LAUNCHER = """#!/bin/sh
exec "{executable}" app
"""


def app_bundle_path(home: Path | None = None) -> Path:
    return Path(home or Path.home()) / "Applications" / f"{APP_NAME}.app"


def helper_path(home: Path | None = None) -> Path:
    return app_bundle_path(home) / "Contents" / "MacOS" / HELPER_NAME


def info_plist() -> dict:
    return {
        "CFBundleName": APP_NAME,
        "CFBundleDisplayName": APP_NAME,
        "CFBundleIdentifier": BUNDLE_ID,
        "CFBundleExecutable": APP_NAME,
        "CFBundlePackageType": "APPL",
        "CFBundleShortVersionString": "0.1.0",
        "CFBundleVersion": "0.1.0",
        "LSMinimumSystemVersion": MINIMUM_MACOS,
        # The local web UI is hosted inside a native desktop window.
        "LSUIElement": False,
        "NSMicrophoneUsageDescription": MICROPHONE_REASON,
        "NSHighResolutionCapable": True,
    }


def install_app_bundle(home: Path | None = None, helper: Path | None = None) -> Path:
    """Create (or refresh) the bundle. Idempotent.

    `helper` is the freshly built `bmcapture`; without it the bundle is still
    created and usable for everything except recording, which is what a machine
    without the Xcode command line tools ends up with.
    """
    bundle = app_bundle_path(home)
    macos_dir = bundle / "Contents" / "MacOS"
    resources = bundle / "Contents" / "Resources"
    macos_dir.mkdir(parents=True, exist_ok=True)
    resources.mkdir(parents=True, exist_ok=True)

    with (bundle / "Contents" / "Info.plist").open("wb") as fh:
        plistlib.dump(info_plist(), fh)

    launcher = macos_dir / APP_NAME
    launcher.write_text(LAUNCHER.format(executable=resolve_executable()))
    _make_executable(launcher)

    if helper is not None:
        installed = macos_dir / HELPER_NAME
        shutil.copyfile(helper, installed)
        _make_executable(installed)

    return bundle


def remove_app_bundle(home: Path | None = None) -> None:
    shutil.rmtree(app_bundle_path(home), ignore_errors=True)


def _make_executable(path: Path) -> None:
    mode = path.stat().st_mode
    path.chmod(mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
