"""Desktop integration: an app icon that behaves the way users expect.

Clicking the icon should Just Work whether or not the server happens to be
running, so `open_app()` is idempotent: connect first, only launch if nothing
answers, then open the browser either way. Double-clicking twice must not
start two servers.
"""
from __future__ import annotations

import os
import shutil
import socket
import subprocess
import sys
import time
import webbrowser
from pathlib import Path

DEFAULT_PORT = 7788
APP_ID = "beyondmeetings"
STARTUP_TIMEOUT = 20.0

ASSETS = Path(__file__).parent / "assets"

# Categories deliberately lists ONE main category: several makes the app
# appear multiple times in the applications menu.
DESKTOP_ENTRY = """[Desktop Entry]
Type=Application
Name=beyondMeetings
GenericName=Meeting Recorder
Comment=Record a meeting and get structured notes in Obsidian
Exec={exec_path} open
Icon={app_id}
Terminal=false
Categories=Office;
Keywords=meeting;recording;transcription;notes;obsidian;
StartupNotify=true
StartupWMClass=beyondmeetings
"""


def desktop_entry_path(home: Path | None = None) -> Path:
    home = Path(home or Path.home())
    return home / ".local" / "share" / "applications" / f"{APP_ID}.desktop"


def icon_install_path(home: Path | None = None) -> Path:
    home = Path(home or Path.home())
    return (
        home / ".local" / "share" / "icons" / "hicolor" / "scalable" / "apps"
        / f"{APP_ID}.svg"
    )


def resolve_executable() -> str:
    """Absolute path to the beyondmeetings command.

    A .desktop file is launched by the session, which often does not have
    ~/.local/bin on PATH — so the path is baked in at install time rather than
    relying on the name resolving.
    """
    found = shutil.which(APP_ID)
    if found:
        return found

    beside = Path(sys.executable).parent / APP_ID
    if beside.is_file():
        return str(beside)

    return str(Path.home() / ".local" / "bin" / APP_ID)


def server_is_running(port: int = DEFAULT_PORT) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        probe.settimeout(0.4)
        return probe.connect_ex(("127.0.0.1", port)) == 0


def wait_for_server(port: int = DEFAULT_PORT, timeout: float = STARTUP_TIMEOUT) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if server_is_running(port):
            return True
        time.sleep(0.25)
    return False


def launch_server(port: int = DEFAULT_PORT, log_dir: Path | None = None) -> int:
    """Start the server detached, so it outlives the launcher process."""
    log_dir = Path(log_dir or Path.home() / ".local" / "share" / APP_ID)
    log_dir.mkdir(parents=True, exist_ok=True)
    log = (log_dir / "server.log").open("a")

    process = subprocess.Popen(
        [resolve_executable(), "serve", "--no-browser", "--port", str(port)],
        stdout=log,
        stderr=subprocess.STDOUT,
        stdin=subprocess.DEVNULL,
        start_new_session=True,  # survives the launcher exiting
    )
    return process.pid


def open_app(
    port: int = DEFAULT_PORT,
    opener=webbrowser.open,
    launcher=launch_server,
    waiter=wait_for_server,
) -> str:
    """Ensure the server is up, then show the page. Safe to call repeatedly."""
    url = f"http://127.0.0.1:{port}/"

    if server_is_running(port):
        opener(url)
        return "already-running"

    launcher(port)
    if not waiter(port):
        raise RuntimeError(
            f"The server did not come up on port {port} within "
            f"{int(STARTUP_TIMEOUT)}s. Check "
            f"~/.local/share/{APP_ID}/server.log"
        )
    opener(url)
    return "started"


def install_desktop_entry(home: Path | None = None) -> Path:
    """Put the icon in the Ubuntu app grid."""
    icon_target = icon_install_path(home)
    icon_target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(ASSETS / "icon.svg", icon_target)

    entry = desktop_entry_path(home)
    entry.parent.mkdir(parents=True, exist_ok=True)
    entry.write_text(
        DESKTOP_ENTRY.format(exec_path=resolve_executable(), app_id=APP_ID),
        encoding="utf-8",
    )
    os.chmod(entry, 0o755)

    # Without this the launcher can take minutes to show up in the app grid.
    for command, args in (
        ("update-desktop-database", [str(entry.parent)]),
        ("gtk-update-icon-cache", ["-f", "-t", str(icon_target.parents[2])]),
    ):
        binary = shutil.which(command)
        if binary:
            subprocess.run([binary, *args], capture_output=True, check=False)

    return entry


def remove_desktop_entry(home: Path | None = None) -> None:
    desktop_entry_path(home).unlink(missing_ok=True)
    icon_install_path(home).unlink(missing_ok=True)
