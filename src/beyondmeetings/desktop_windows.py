"""Windows desktop integration: the Start Menu entry and the login shortcut.

The macOS counterpart is desktop_macos.py; this module plays the same role and
is imported only from Windows branches. Nothing here runs on Linux.

Shortcuts are .lnk files, a shell binary format, so writing one means asking
Windows to do it. That is delegated to a short PowerShell snippet through an
injectable runner — the shape audio/windows.py already uses for its capture
worker. Two things fall out of that choice: pywin32 stays out of the dependency
list, and the script-building logic is a pure function, so it is unit-tested on
whatever platform CI happens to be running.
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

APP_NAME = "beyondMeetings"
SHORTCUT_NAME = f"{APP_NAME}.lnk"
DESCRIPTION = "Private meeting recorder and local notes app"

# 7 = minimized. The login shortcut targets pythonw.exe, which shows no window
# at all, but a window style is part of a .lnk and an explicit value keeps the
# generated script identical between runs.
WINDOW_MINIMIZED = 7


class PowerShellRunner:
    """Runs a PowerShell snippet. Replaced by a fake in tests."""

    def run(self, script: str) -> None:
        subprocess.run(
            [
                "powershell", "-NoProfile", "-NonInteractive",
                "-ExecutionPolicy", "Bypass", "-Command", script,
            ],
            check=True,
            capture_output=True,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )


def _roaming_appdata(home: Path | None = None) -> Path:
    """Where Windows keeps per-user roaming data.

    APPDATA is honoured first so tests (and the test sandbox in conftest) can
    redirect it; the literal layout is the fallback for a bare environment.
    """
    if home is None:
        env = os.environ.get("APPDATA")
        if env:
            return Path(env)
        home = Path.home()
    return Path(home) / "AppData" / "Roaming"


def start_menu_dir(home: Path | None = None) -> Path:
    return (
        _roaming_appdata(home)
        / "Microsoft" / "Windows" / "Start Menu" / "Programs"
    )


def startup_dir(home: Path | None = None) -> Path:
    return start_menu_dir(home) / "Startup"


def shortcut_path(home: Path | None = None) -> Path:
    return start_menu_dir(home) / SHORTCUT_NAME


def startup_shortcut_path(home: Path | None = None) -> Path:
    return startup_dir(home) / SHORTCUT_NAME


def command_path() -> Path:
    """The installed console script, next to the venv's python.exe."""
    return Path(sys.executable).with_name("beyondmeetings.exe")


def windowless_python() -> Path:
    """pythonw.exe if this interpreter has one, else the interpreter itself."""
    candidate = Path(sys.executable).with_name("pythonw.exe")
    return candidate if candidate.is_file() else Path(sys.executable)


def _ps_quote(value: object) -> str:
    """Single-quote for PowerShell, doubling embedded quotes.

    Usernames legitimately contain spaces and apostrophes, so
    C:\\Users\\O'Brien Smith\\... has to survive the round trip.
    """
    return "'" + str(value).replace("'", "''") + "'"


def build_shortcut_script(
    link: Path,
    target: Path,
    arguments: str = "",
    working_dir: Path | None = None,
    description: str = DESCRIPTION,
    window_style: int = 1,
) -> str:
    """The PowerShell that creates one .lnk. Pure, so it is testable anywhere."""
    working_dir = working_dir or target.parent
    lines = [
        "$ErrorActionPreference = 'Stop'",
        f"$dir = {_ps_quote(link.parent)}",
        "if (-not (Test-Path $dir)) "
        "{ New-Item -ItemType Directory -Force -Path $dir | Out-Null }",
        "$shell = New-Object -ComObject WScript.Shell",
        f"$link = $shell.CreateShortcut({_ps_quote(link)})",
        f"$link.TargetPath = {_ps_quote(target)}",
        f"$link.Arguments = {_ps_quote(arguments)}",
        f"$link.WorkingDirectory = {_ps_quote(working_dir)}",
        f"$link.Description = {_ps_quote(description)}",
        f"$link.WindowStyle = {int(window_style)}",
        "$link.Save()",
    ]
    return "; ".join(lines)


def install_shortcut(
    home: Path | None = None,
    runner: PowerShellRunner | None = None,
    target: Path | None = None,
) -> Path:
    """Create the Start Menu entry. Returns where it went."""
    link = shortcut_path(home)
    runner = runner or PowerShellRunner()
    runner.run(
        build_shortcut_script(
            link,
            target or command_path(),
            arguments="app",
        )
    )
    return link


def install_startup_shortcut(
    home: Path | None = None,
    runner: PowerShellRunner | None = None,
    target: Path | None = None,
) -> Path:
    """Start the background server (and tray indicator) at login."""
    link = startup_shortcut_path(home)
    runner = runner or PowerShellRunner()
    runner.run(
        build_shortcut_script(
            link,
            target or windowless_python(),
            arguments="-m beyondmeetings serve --no-browser",
            description=f"{APP_NAME} background service",
            window_style=WINDOW_MINIMIZED,
        )
    )
    return link


def remove_shortcut(home: Path | None = None) -> None:
    shortcut_path(home).unlink(missing_ok=True)


def remove_startup_shortcut(home: Path | None = None) -> None:
    startup_shortcut_path(home).unlink(missing_ok=True)
