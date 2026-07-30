"""Optional system-tray icon.

pystray pulls a GTK/AppIndicator stack that behaves differently across desktop
environments, so it is an extra rather than a hard dependency. The app page at
localhost:7788 is fully usable without it.
"""
from __future__ import annotations

import threading
import webbrowser

try:
    import pystray
except Exception:  # ImportError, or a missing display backend
    pystray = None

try:
    from PIL import Image, ImageDraw
except Exception:
    Image = ImageDraw = None

TRAY_HINT = (
    "The tray needs extra packages. Install them with:\n"
    "  pip install 'beyondmeetings[tray]'\n"
    "The app page at http://127.0.0.1:7788 works without it."
)

SIZE = 64
IDLE_COLOUR = (99, 102, 241, 255)
LIVE_COLOUR = (220, 38, 38, 255)


def tray_available() -> bool:
    return pystray is not None and Image is not None


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


def run_tray(url: str, session=None) -> None:
    """Blocking. Runs the tray icon until the user quits."""
    if not tray_available():
        raise RuntimeError(TRAY_HINT)

    def open_app(_icon=None, _item=None):
        webbrowser.open(url)

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
            # Already recording, or nothing to stop — the page shows why.
            pass
        icon.icon = build_icon_image(session.status()["recording"])

    def watch(icon):
        icon.visible = True
        stop = threading.Event()
        while not stop.wait(2):
            if session is not None:
                icon.icon = build_icon_image(session.status()["recording"])

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
