"""Global recording indicator for the operating-system panel or tray.

Linux prefers Ayatana AppIndicator, which GNOME's AppIndicator extension puts
in the top panel. Windows and macOS (and non-GNOME Linux desktops) fall back
to pystray. Both watch the same SessionManager used by the web UI.
"""
from __future__ import annotations

import os
import sys
import threading
from pathlib import Path

from .desktop import open_browser


def _configure_private_typelib() -> None:
    """Make the no-sudo AppIndicator binding visible to PyGObject."""
    app_home = Path(
        os.environ.get(
            "BEYONDMEETINGS_HOME",
            Path.home() / ".local" / "share" / "beyondmeetings-app",
        )
    )
    candidates = list(
        (app_home / "indicator" / "usr" / "lib").glob("*/girepository-1.0")
    )
    if not candidates:
        return
    existing = os.environ.get("GI_TYPELIB_PATH", "")
    paths = [str(candidates[0]), *[p for p in existing.split(os.pathsep) if p]]
    os.environ["GI_TYPELIB_PATH"] = os.pathsep.join(paths)


_configure_private_typelib()

try:
    import gi

    gi.require_version("Gtk", "3.0")
    gi.require_version("AyatanaAppIndicator3", "0.1")
    from gi.repository import AyatanaAppIndicator3, GLib, Gtk
except (ImportError, ValueError):
    AyatanaAppIndicator3 = GLib = Gtk = None

try:
    import pystray
except Exception:  # ImportError, or a missing display backend
    pystray = None

try:
    from PIL import Image, ImageDraw
except Exception:
    Image = ImageDraw = None

TRAY_HINT = (
    "The global recording indicator is unavailable. On Ubuntu/Debian install:\n"
    "  sudo apt-get install gir1.2-ayatanaappindicator3-0.1\n"
    "On other systems install: pip install 'beyondmeetings[tray]'\n"
    "The app page at http://127.0.0.1:7788 works without it."
)

SIZE = 64
IDLE_COLOUR = (99, 102, 241, 255)
LIVE_COLOUR = (220, 38, 38, 255)
ASSETS = Path(__file__).parent / "assets"


def _ayatana_available() -> bool:
    return all(value is not None for value in (AyatanaAppIndicator3, GLib, Gtk))


def tray_available() -> bool:
    return _ayatana_available() or (pystray is not None and Image is not None)


def _clock(seconds: int) -> str:
    seconds = max(0, int(seconds or 0))
    hours, remainder = divmod(seconds, 3600)
    minutes, seconds = divmod(remainder, 60)
    return (
        f"{hours}:{minutes:02d}:{seconds:02d}"
        if hours
        else f"{minutes:02d}:{seconds:02d}"
    )


def indicator_view(status: dict | None) -> dict:
    """Translate session state into consistent panel text and actions."""
    status = status or {}
    recording = bool(status.get("recording"))
    if recording:
        elapsed = _clock(status.get("elapsed_seconds", 0))
        name = status.get("name") or "Meeting"
        return {
            "recording": True,
            "label": f"REC {elapsed}",
            "title": f"● Recording — {name} ({elapsed})",
            "action": "Stop recording",
        }
    phase = status.get("phase") or "idle"
    busy = phase in {"stopping", "transcribing", "analysing"}
    return {
        "recording": False,
        "label": "",
        "title": "Processing meeting…" if busy else "Not recording",
        "action": "Open beyondMeetings" if busy else "Start recording",
    }


def build_icon_image(recording: bool = False):
    if Image is None:
        raise RuntimeError(TRAY_HINT)
    image = Image.new("RGBA", (SIZE, SIZE), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    draw.ellipse(
        [6, 6, SIZE - 6, SIZE - 6], fill=LIVE_COLOUR if recording else IDLE_COLOUR
    )
    if recording:
        # A white square reads as "stop" at 22 pixels; a dot does not.
        draw.rectangle([24, 24, SIZE - 24, SIZE - 24], fill=(255, 255, 255, 255))
    return image


def _run_ayatana(url: str, session) -> None:
    idle_icon = str(ASSETS / "indicator-idle.svg")
    live_icon = str(ASSETS / "indicator-recording.svg")
    indicator = AyatanaAppIndicator3.Indicator.new(
        "beyondmeetings-recording",
        idle_icon,
        AyatanaAppIndicator3.IndicatorCategory.APPLICATION_STATUS,
    )
    indicator.set_status(AyatanaAppIndicator3.IndicatorStatus.ACTIVE)
    indicator.set_title("beyondMeetings")

    menu = Gtk.Menu()
    status_item = Gtk.MenuItem(label="Not recording")
    status_item.set_sensitive(False)
    toggle_item = Gtk.MenuItem(label="Start recording")
    open_item = Gtk.MenuItem(label="Open beyondMeetings")
    quit_item = Gtk.MenuItem(label="Quit beyondMeetings")

    def open_app(*_args):
        open_browser(url)

    def toggle(*_args):
        view = indicator_view(session.status())
        try:
            if view["recording"]:
                session.stop()
            elif session.status().get("phase") not in {
                "stopping", "transcribing", "analysing"
            }:
                session.start("")
            else:
                open_app()
        except RuntimeError:
            open_app()

    def quit_app(*_args):
        Gtk.main_quit()

    toggle_item.connect("activate", toggle)
    open_item.connect("activate", open_app)
    quit_item.connect("activate", quit_app)
    for item in (
        status_item,
        Gtk.SeparatorMenuItem(),
        toggle_item,
        open_item,
        Gtk.SeparatorMenuItem(),
        quit_item,
    ):
        menu.append(item)
    menu.show_all()
    indicator.set_menu(menu)

    def refresh() -> bool:
        view = indicator_view(session.status())
        indicator.set_icon_full(live_icon if view["recording"] else idle_icon, "")
        # GNOME displays this beside the icon, making recording unmissable even
        # when the beyondMeetings window is covered by another application.
        indicator.set_label(view["label"], "REC 00:00:00")
        status_item.set_label(view["title"])
        toggle_item.set_label(view["action"])
        return True

    refresh()
    GLib.timeout_add_seconds(1, refresh)
    Gtk.main()


def _run_pystray(url: str, session=None) -> None:
    if pystray is None or Image is None:
        raise RuntimeError(TRAY_HINT)

    def open_app(_icon=None, _item=None):
        open_browser(url)

    def toggle(icon, _item=None):
        if session is None:
            open_app()
            return
        try:
            if session.status()["recording"]:
                session.stop()
            else:
                session.start("")
        except RuntimeError:
            pass
        icon.icon = build_icon_image(session.status()["recording"])

    def watch(icon):
        icon.visible = True
        stop = threading.Event()
        while not stop.wait(1):
            if session is not None:
                view = indicator_view(session.status())
                icon.icon = build_icon_image(view["recording"])
                icon.title = (
                    f"beyondMeetings — {view['title']}"
                    if view["recording"]
                    else "beyondMeetings"
                )

    items = [pystray.MenuItem("Open beyondMeetings", open_app)]
    if session is not None:
        items.insert(0, pystray.MenuItem("Start / stop recording", toggle))
    items.append(pystray.MenuItem("Quit", lambda icon, _=None: icon.stop()))

    icon = pystray.Icon(
        "beyondmeetings",
        build_icon_image(False),
        "beyondMeetings",
        pystray.Menu(*items),
    )
    icon.run(setup=watch if session is not None else None)


def run_tray(url: str, session=None) -> None:
    """Blocking. Run the best global indicator available on this platform."""
    if _ayatana_available() and sys.platform.startswith("linux") and session is not None:
        _run_ayatana(url, session)
        return
    _run_pystray(url, session)
