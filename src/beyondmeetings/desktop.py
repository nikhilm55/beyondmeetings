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
import threading
import time
import webbrowser
from pathlib import Path

from .tools import which_tool

DEFAULT_PORT = 7788
APP_ID = "beyondmeetings"
STARTUP_TIMEOUT = 20.0
POLL_INTERVAL = 0.25

ASSETS = Path(__file__).parent / "assets"

# Categories deliberately lists ONE main category: several makes the app
# appear multiple times in the applications menu.
DESKTOP_ENTRY = """[Desktop Entry]
Type=Application
Name=beyondMeetings
GenericName=Meeting Recorder
Comment=Record meetings and keep structured notes locally
Exec={exec_path} app
Icon={app_id}
Terminal=false
Categories=Office;
Keywords=meeting;recording;transcription;notes;tasks;
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


def resolve_executable(platform: str | None = None) -> str:
    """Absolute path to the beyondmeetings command.

    A .desktop file is launched by the session, which often does not have
    ~/.local/bin on PATH — so the path is baked in at install time rather than
    relying on the name resolving. The Windows counterpart is the Start Menu
    shortcut, launched by Explorer with whatever PATH the user's profile has.

    On Windows the console script is `beyondmeetings.exe`, so the bare name
    never matched as a file and the last resort was a POSIX path that cannot
    exist there. `which_tool` already knows to look beside the interpreter and
    in the application's own bin directory, which is exactly where both
    installers put it.
    """
    platform = platform if platform is not None else sys.platform

    if platform == "win32":
        # The sibling .exe is checked before PATH on purpose. The bin
        # directory both Windows installers create holds a *.cmd* shim, and
        # subprocess goes through CreateProcess, which cannot launch a batch
        # file — so a PATH hit there would be worse than no hit at all.
        beside = Path(sys.executable).parent / f"{APP_ID}.exe"
        if beside.is_file():
            return str(beside)
        found = which_tool(APP_ID, platform=platform)
        if found and found.lower().endswith(".exe"):
            return found
        # Absolute either way: the venv's Scripts directory is where pip put
        # the console script, whether or not this interpreter can see it.
        return str(beside)

    found = shutil.which(APP_ID)
    if found:
        return found

    beside = Path(sys.executable).parent / APP_ID
    if beside.is_file():
        return str(beside)

    return str(Path.home() / ".local" / "bin" / APP_ID)


def server_log_dir(platform: str | None = None) -> Path:
    """Where the detached server's output goes.

    Windows has no ~/.local/share, and the message pointing a user at the log
    has to name a path that exists on their machine.
    """
    platform = platform if platform is not None else sys.platform
    if platform == "win32":
        local = os.environ.get("LOCALAPPDATA")
        base = Path(local) if local else Path.home() / "AppData" / "Local"
        return base / APP_ID / "logs"
    return Path.home() / ".local" / "share" / APP_ID


def server_is_running(port: int = DEFAULT_PORT) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        probe.settimeout(0.4)
        return probe.connect_ex(("127.0.0.1", port)) == 0


def wait_until(predicate, timeout: float = STARTUP_TIMEOUT) -> bool:
    """Poll `predicate` until it holds, or `timeout` passes."""
    deadline = time.monotonic() + timeout
    while True:
        if predicate():
            return True
        if time.monotonic() >= deadline:
            return False
        time.sleep(POLL_INTERVAL)


def wait_for_server(port: int = DEFAULT_PORT, timeout: float = STARTUP_TIMEOUT) -> bool:
    """Wait for *something* to answer on `port`.

    Only for the servers we launch as a separate process, where the port is
    the one signal we have. A server running in this process should be waited
    for by its own `started` flag instead — see `open_browser_when_ready`.
    """
    return wait_until(lambda: server_is_running(port), timeout)


def open_browser(url: str, spawn=None, browser_check=None) -> bool:
    """Hand `url` to the browser without inheriting the browser's own output.

    `webbrowser.open` starts the browser with our stdout and stderr, so
    anything it prints looks like it came from us. A Chromium launched while
    an instance is already running forwards the URL, prints "Opening in
    existing browser session." and exits at once — and on the way out logs
    `ERROR:content/zygote/zygote_linux.cc:662] write: Broken pipe (32)`.
    That is harmless browser teardown noise, but printed in the middle of
    `install.sh` it reads as beyondMeetings crashing. Going through a child
    interpreter lets those two descriptors point at /dev/null instead.

    False means the URL was not handed over: there is no browser on this
    machine (a headless box, or an SSH session with no BROWSER), or the child
    could not be spawned. True is fire-and-forget — the child is not waited
    on, so a browser that starts and then fails is not reported.
    """
    try:
        (browser_check or webbrowser.get)()
    except webbrowser.Error:
        return False

    spawn = spawn or subprocess.Popen
    try:
        spawn(
            [sys.executable, "-m", "webbrowser", url],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )
    except OSError:
        return False
    return True


def _warn(message: str) -> None:
    print(message, file=sys.stderr)


def open_browser_when_ready(
    url: str,
    ready,
    timeout: float = STARTUP_TIMEOUT,
    cancelled=None,
    opener=None,
    reporter=None,
) -> threading.Thread:
    """Open `url` from a watcher thread, once `ready()` says the server is up.

    `setup` runs the server in this process and blocks in uvicorn, so there is
    no moment between "socket bound" and "blocked" at which to open the
    browser — it used to open it first and hope. That is a race the browser
    wins whenever it is already running: it navigates in milliseconds and
    lands on ERR_CONNECTION_REFUSED while uvicorn is still binding, which is
    why this only showed up on some machines (a browser that has to cold-start
    takes seconds and loses the race).

    `ready` is asked about *our* server — uvicorn's `started` — rather than
    about the port, because a stranger already listening on it would otherwise
    have our browser opened onto their page. `cancelled` lets the caller call
    the wait off once its server has stopped for good.
    """
    def watch() -> None:
        report = reporter or _warn
        deadline = time.monotonic() + timeout
        while not (cancelled and cancelled()):
            if ready():
                if not (opener or open_browser)(url):
                    report(f"No browser could be opened — go to {url}")
                return
            if time.monotonic() >= deadline:
                report(
                    f"The server did not come up within {int(timeout)}s — "
                    f"go to {url} once it does."
                )
                return
            time.sleep(POLL_INTERVAL)

    thread = threading.Thread(target=watch, name="open-browser", daemon=True)
    thread.start()
    return thread


def detach_flags(platform: str | None = None) -> int:
    """CreateProcess flags that make a child outlive us, and show no console.

    `start_new_session` is a POSIX-only setting — subprocess ignores it on
    Windows — so without these the server was a child of a launcher that was
    about to exit, and it flashed a console window on the way up.
    """
    platform = platform if platform is not None else sys.platform
    if platform != "win32":
        return 0
    return (
        getattr(subprocess, "DETACHED_PROCESS", 0)
        | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
        | getattr(subprocess, "CREATE_NO_WINDOW", 0)
    )


def launch_server(port: int = DEFAULT_PORT, log_dir: Path | None = None) -> int:
    """Start the server detached, so it outlives the launcher process."""
    log_dir = Path(log_dir or server_log_dir())
    log_dir.mkdir(parents=True, exist_ok=True)
    log = (log_dir / "server.log").open("a", encoding="utf-8")

    process = subprocess.Popen(
        [resolve_executable(), "serve", "--no-browser", "--port", str(port)],
        stdout=log,
        stderr=subprocess.STDOUT,
        stdin=subprocess.DEVNULL,
        start_new_session=True,  # survives the launcher exiting (POSIX)
        creationflags=detach_flags(),  # the same thing on Windows
    )
    return process.pid


def open_app(
    port: int = DEFAULT_PORT,
    opener=open_browser,
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
            f"{server_log_dir() / 'server.log'}"
        )
    opener(url)
    return "started"


def report_headless(
    message: str,
    title: str = "beyondMeetings",
    platform: str | None = None,
    box=None,
) -> bool:
    """Show a message box when there is no console to print to.

    The Windows app icon runs `pythonw.exe -m beyondmeetings open`, and
    pythonw has no stdout or stderr at all. Without this, every way that
    launch can fail — the port taken by something else, a half-built
    environment — looks identical to the user: they double-click the icon and
    nothing whatsoever happens.

    False means nothing was shown, and the caller's ordinary error path still
    applies. Nothing here is allowed to raise: it runs while reporting a
    failure, and a failure to report a failure helps nobody.
    """
    platform = platform if platform is not None else sys.platform
    if platform != "win32" or sys.stdout is not None:
        return False

    if box is None:
        try:
            import ctypes

            box = ctypes.windll.user32.MessageBoxW
        except (ImportError, AttributeError, OSError):
            return False
    try:
        box(None, message, title, 0x10)  # MB_OK | MB_ICONERROR
    except Exception:
        return False
    return True


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
