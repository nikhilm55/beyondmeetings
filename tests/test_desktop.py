"""Desktop launcher: clicking the icon must be idempotent."""
import pytest

from beyondmeetings.config import Config
from beyondmeetings.desktop import (
    APP_ID, DEFAULT_PORT, desktop_entry_path, icon_install_path,
    install_desktop_entry, open_app, remove_desktop_entry, resolve_executable,
)
from beyondmeetings.doctor.desktop import DesktopLauncherCheck


def test_open_reuses_a_running_server(monkeypatch):
    """Double-clicking the icon twice must not start two servers."""
    opened, launched = [], []
    monkeypatch.setattr("beyondmeetings.desktop.server_is_running", lambda p=0: True)
    outcome = open_app(
        opener=opened.append,
        launcher=lambda p: launched.append(p),
        waiter=lambda p, timeout=0: True,
    )
    assert outcome == "already-running"
    assert launched == [], "must not launch when one is already up"
    assert opened == [f"http://127.0.0.1:{DEFAULT_PORT}/"]


def test_open_starts_the_server_when_nothing_is_listening(monkeypatch):
    opened, launched = [], []
    monkeypatch.setattr("beyondmeetings.desktop.server_is_running", lambda p=0: False)
    outcome = open_app(
        opener=opened.append,
        launcher=lambda p: launched.append(p),
        waiter=lambda p, timeout=0: True,
    )
    assert outcome == "started"
    assert launched == [DEFAULT_PORT]
    assert opened


def test_open_opens_the_browser_after_the_server_is_up(monkeypatch):
    """Opening too early shows a connection error to the user."""
    order = []
    monkeypatch.setattr("beyondmeetings.desktop.server_is_running", lambda p=0: False)
    open_app(
        opener=lambda url: order.append("open"),
        launcher=lambda p: order.append("launch"),
        waiter=lambda p, timeout=0: order.append("wait") or True,
    )
    assert order == ["launch", "wait", "open"]


def test_open_reports_a_server_that_never_came_up(monkeypatch):
    monkeypatch.setattr("beyondmeetings.desktop.server_is_running", lambda p=0: False)
    with pytest.raises(RuntimeError, match="did not come up"):
        open_app(opener=lambda u: None, launcher=lambda p: None,
                 waiter=lambda p, timeout=0: False)


def test_open_does_not_open_a_browser_on_failure(monkeypatch):
    opened = []
    monkeypatch.setattr("beyondmeetings.desktop.server_is_running", lambda p=0: False)
    with pytest.raises(RuntimeError):
        open_app(opener=opened.append, launcher=lambda p: None,
                 waiter=lambda p, timeout=0: False)
    assert opened == []


def test_install_writes_both_the_entry_and_the_icon(tmp_path):
    install_desktop_entry(tmp_path)
    assert desktop_entry_path(tmp_path).is_file()
    assert icon_install_path(tmp_path).is_file()


def test_entry_is_a_valid_desktop_file(tmp_path):
    install_desktop_entry(tmp_path)
    text = desktop_entry_path(tmp_path).read_text()
    assert text.startswith("[Desktop Entry]")
    assert "Type=Application" in text
    assert f"Icon={APP_ID}" in text
    assert "Terminal=false" in text


def test_entry_calls_native_app_not_browser_launcher(tmp_path):
    install_desktop_entry(tmp_path)
    text = desktop_entry_path(tmp_path).read_text()
    assert " app" in text
    assert "serve" not in text


def test_entry_uses_an_absolute_executable_path(tmp_path):
    """A desktop session often lacks ~/.local/bin on PATH."""
    install_desktop_entry(tmp_path)
    exec_line = next(
        l for l in desktop_entry_path(tmp_path).read_text().splitlines()
        if l.startswith("Exec=")
    )
    assert exec_line.removeprefix("Exec=").startswith("/")


def test_icon_is_scalable_svg(tmp_path):
    install_desktop_entry(tmp_path)
    icon = icon_install_path(tmp_path)
    assert icon.suffix == ".svg"
    assert "scalable" in str(icon)
    assert icon.read_text().lstrip().startswith("<svg")


def test_install_is_idempotent(tmp_path):
    install_desktop_entry(tmp_path)
    install_desktop_entry(tmp_path)
    apps = list((tmp_path / ".local/share/applications").glob("*.desktop"))
    assert len(apps) == 1


def test_remove_deletes_both(tmp_path):
    install_desktop_entry(tmp_path)
    remove_desktop_entry(tmp_path)
    assert not desktop_entry_path(tmp_path).exists()
    assert not icon_install_path(tmp_path).exists()


def test_resolve_executable_is_absolute():
    assert resolve_executable().startswith("/")


def test_check_reports_missing_then_ok(tmp_path):
    check = DesktopLauncherCheck(Config(), home=tmp_path)
    assert check.detect().status == "missing"
    assert check.fix().status == "ok"
    assert check.detect().status == "ok"


def test_check_is_optional(tmp_path):
    assert DesktopLauncherCheck(Config(), home=tmp_path).required is False


# --- The in-process servers (`setup`, `serve`) raced the browser ---

URL = "http://127.0.0.1:7788/setup"


def test_open_browser_when_ready_waits_before_opening():
    """A browser told to navigate before uvicorn binds gets ERR_CONNECTION_REFUSED."""
    from beyondmeetings.desktop import open_browser_when_ready

    order = []
    open_browser_when_ready(
        URL,
        ready=lambda: order.append("ready") or True,
        opener=lambda url: order.append("open") or True,
    ).join(timeout=5)
    assert order == ["ready", "open"]


def test_open_browser_when_ready_gives_up_if_the_server_never_starts():
    """Better no tab at all than a tab showing a connection error."""
    from beyondmeetings.desktop import open_browser_when_ready

    opened, reported = [], []
    open_browser_when_ready(
        URL, ready=lambda: False, timeout=0.05,
        opener=opened.append, reporter=reported.append,
    ).join(timeout=5)
    assert opened == []
    assert reported, "giving up silently leaves the user staring at nothing"
    assert URL in reported[0], "the message must say where to go instead"


def test_open_browser_when_ready_says_so_when_no_browser_could_be_opened():
    from beyondmeetings.desktop import open_browser_when_ready

    reported = []
    open_browser_when_ready(
        URL, ready=lambda: True, opener=lambda url: False, reporter=reported.append,
    ).join(timeout=5)
    assert reported and URL in reported[0]


def test_open_browser_when_ready_stops_waiting_once_the_server_is_gone():
    """A server that failed to bind is never coming up — do not wait out the timeout."""
    from beyondmeetings.desktop import open_browser_when_ready

    opened, reported = [], []
    thread = open_browser_when_ready(
        URL, ready=lambda: False, timeout=60, cancelled=lambda: True,
        opener=opened.append, reporter=reported.append,
    )
    thread.join(timeout=5)
    assert not thread.is_alive(), "the watcher outlived the server it was waiting for"
    assert opened == [] and reported == []


def test_open_browser_when_ready_does_not_block_the_caller():
    """The caller's next move is uvicorn.run — the wait cannot happen first."""
    import threading

    from beyondmeetings.desktop import open_browser_when_ready

    released = threading.Event()
    thread = open_browser_when_ready(
        URL, ready=released.is_set, opener=lambda url: True,
    )
    assert thread.is_alive(), "waiting must happen off the calling thread"
    released.set()
    thread.join(timeout=5)


def test_wait_until_returns_as_soon_as_the_predicate_holds():
    import time

    from beyondmeetings.desktop import wait_until

    started = time.monotonic()
    assert wait_until(lambda: True, timeout=30) is True
    assert time.monotonic() - started < 1


def test_wait_until_gives_up_at_the_timeout():
    from beyondmeetings.desktop import wait_until

    assert wait_until(lambda: False, timeout=0.05) is False


# --- The browser's own stderr was being printed as if it were ours ---

def test_open_browser_discards_the_browsers_output():
    """Chromium logs a zygote 'Broken pipe' on exit; inherited, it reads as our crash."""
    import subprocess

    from beyondmeetings.desktop import open_browser

    calls = []
    assert open_browser(URL, spawn=lambda *a, **kw: calls.append((a, kw)),
                        browser_check=lambda: None) is True
    (argv,), kwargs = calls[0]
    assert kwargs["stdout"] is subprocess.DEVNULL
    assert kwargs["stderr"] is subprocess.DEVNULL
    assert URL in argv


def test_open_browser_survives_a_browser_that_cannot_be_launched():
    from beyondmeetings.desktop import open_browser

    def boom(*a, **kw):
        raise OSError("no such file")

    assert open_browser(URL, spawn=boom, browser_check=lambda: None) is False


def test_open_browser_reports_when_there_is_no_browser_at_all():
    """`webbrowser.open` returned False here; a fire-and-forget child cannot.

    Headless boxes and SSH sessions have no browser, and the caller has to be
    able to tell — otherwise it claims a tab was opened that never was.
    """
    import webbrowser

    from beyondmeetings.desktop import open_browser

    spawned = []

    def no_browser():
        raise webbrowser.Error("could not locate runnable browser")

    assert open_browser(URL, spawn=spawned.append, browser_check=no_browser) is False
    assert spawned == [], "nothing to hand the URL to — do not spawn a child"


def test_open_browser_really_reaches_the_browser(tmp_path, monkeypatch):
    """End-to-end: catches a wrong child-process invocation, which mocks cannot.

    BROWSER runs the *interpreter* rather than a shell script directly: a file
    under /tmp is not executable on a `noexec` mount, and `webbrowser` reacts
    to a browser it cannot launch by silently trying the next one it knows —
    which on a developer machine means really opening their real browser.
    """
    import sys
    import time
    import webbrowser

    from beyondmeetings.desktop import open_browser

    marker = tmp_path / "opened.txt"
    fake = tmp_path / "fake_browser.py"
    fake.write_text(
        "import pathlib, sys\n"
        f"pathlib.Path({str(marker)!r}).write_text(sys.argv[1])\n"
    )
    monkeypatch.setenv("BROWSER", f"{sys.executable} {fake} %s")
    # BROWSER is read once per process, on first use — which may already have
    # happened in another test.
    monkeypatch.setattr(webbrowser, "_tryorder", None)

    assert open_browser(URL) is True
    deadline = time.monotonic() + 15
    while time.monotonic() < deadline and not marker.exists():
        time.sleep(0.05)
    assert marker.exists(), "the child interpreter never handed the URL over"
    assert marker.read_text() == URL
