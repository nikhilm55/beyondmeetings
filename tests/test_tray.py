import pytest

from beyondmeetings.tray import (
    TRAY_HINT, build_icon_image, indicator_view, tray_available,
)


def test_reports_availability_honestly():
    assert isinstance(tray_available(), bool)


def test_hint_names_the_extra():
    assert "beyondmeetings[tray]" in TRAY_HINT


def test_hint_says_the_page_still_works():
    assert "works without it" in TRAY_HINT


def test_icon_image_is_square_when_pillow_is_present():
    pytest.importorskip("PIL")
    image = build_icon_image(recording=False)
    assert image.size[0] == image.size[1]


def test_recording_icon_differs_from_idle():
    pytest.importorskip("PIL")
    idle = build_icon_image(recording=False).tobytes()
    live = build_icon_image(recording=True).tobytes()
    assert idle != live


def test_build_icon_raises_the_hint_without_pillow(monkeypatch):
    import beyondmeetings.tray as tray_mod
    monkeypatch.setattr(tray_mod, "Image", None)
    with pytest.raises(RuntimeError, match=r"beyondmeetings\[tray\]"):
        tray_mod.build_icon_image()


def test_run_tray_without_pystray_raises_the_hint(monkeypatch):
    import beyondmeetings.tray as tray_mod
    monkeypatch.setattr(tray_mod, "pystray", None)
    monkeypatch.setattr(tray_mod, "AyatanaAppIndicator3", None)
    monkeypatch.setattr(tray_mod, "GLib", None)
    monkeypatch.setattr(tray_mod, "Gtk", None)
    with pytest.raises(RuntimeError, match=r"beyondmeetings\[tray\]"):
        tray_mod.run_tray("http://127.0.0.1:7788")


def _fake_pystray(monkeypatch):
    """A pystray that builds the menu without needing a display."""
    import types

    import beyondmeetings.tray as tray_mod

    class FakeMenuItem:
        def __init__(self, label, action):
            self.label, self.action = label, action

    items = []

    class FakeIcon:
        def __init__(self, name, image, title, menu):
            items.extend(menu)

        def run(self, setup=None):
            pass  # the real one blocks until the user quits

    monkeypatch.setattr(tray_mod, "pystray", types.SimpleNamespace(
        MenuItem=FakeMenuItem, Menu=lambda *menu: list(menu), Icon=FakeIcon,
    ))
    monkeypatch.setattr(tray_mod, "Image", object())
    monkeypatch.setattr(tray_mod, "AyatanaAppIndicator3", None)
    monkeypatch.setattr(tray_mod, "GLib", None)
    monkeypatch.setattr(tray_mod, "Gtk", None)
    monkeypatch.setattr(tray_mod, "build_icon_image", lambda recording=False: None)
    return items


def test_open_item_hands_the_url_to_the_detached_opener(monkeypatch):
    """`webbrowser.open` in the tray had both of the problems it has elsewhere.

    The callback runs inside the long-lived `serve` process, so the browser's
    own stderr lands in server.log; and for a GenericBrowser `webbrowser.open`
    ends in `p.wait()`, which freezes pystray's menu thread until the browser
    exits.
    """
    import beyondmeetings.tray as tray_mod

    items = _fake_pystray(monkeypatch)
    opened = []
    monkeypatch.setattr(tray_mod, "open_browser", lambda url: opened.append(url))

    tray_mod.run_tray("http://127.0.0.1:7788/")
    item = next(i for i in items if i.label == "Open beyondMeetings")
    item.action()

    assert opened == ["http://127.0.0.1:7788/"]


def test_tray_unavailable_when_either_dependency_is_missing(monkeypatch):
    import beyondmeetings.tray as tray_mod
    monkeypatch.setattr(tray_mod, "pystray", object())
    monkeypatch.setattr(tray_mod, "Image", None)
    monkeypatch.setattr(tray_mod, "AyatanaAppIndicator3", None)
    monkeypatch.setattr(tray_mod, "GLib", None)
    monkeypatch.setattr(tray_mod, "Gtk", None)
    assert tray_available() is False


def test_indicator_view_makes_live_recording_unmissable():
    view = indicator_view({
        "recording": True,
        "name": "Design review",
        "elapsed_seconds": 65,
    })
    assert view == {
        "recording": True,
        "label": "REC 01:05",
        "title": "● Recording — Design review (01:05)",
        "action": "Stop recording",
    }


def test_indicator_view_is_quiet_when_idle():
    view = indicator_view({"recording": False, "phase": "idle"})
    assert view["label"] == ""
    assert view["title"] == "Not recording"
    assert view["action"] == "Start recording"


def test_indicator_view_does_not_offer_start_while_processing():
    view = indicator_view({"recording": False, "phase": "transcribing"})
    assert view["title"] == "Processing meeting…"
    assert view["action"] == "Open beyondMeetings"
