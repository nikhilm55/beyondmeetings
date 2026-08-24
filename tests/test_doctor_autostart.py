from beyondmeetings.config import Config
from beyondmeetings.doctor.autostart import AutostartCheck, refresh_installed_autostart


def test_missing_when_no_desktop_entry(tmp_path):
    assert AutostartCheck(Config(), home=tmp_path).detect().status == "missing"


def test_fix_writes_a_desktop_entry(tmp_path):
    check = AutostartCheck(Config(), home=tmp_path)
    assert check.fix().status == "ok"
    entry = tmp_path / ".config" / "autostart" / "beyondmeetings.desktop"
    assert entry.is_file()
    assert "beyondmeetings" in entry.read_text()


def test_entry_is_a_valid_desktop_file(tmp_path):
    AutostartCheck(Config(), home=tmp_path).fix()
    text = (tmp_path / ".config" / "autostart" / "beyondmeetings.desktop").read_text()
    assert text.startswith("[Desktop Entry]")
    assert "Type=Application" in text
    assert "Exec=" in text


def test_entry_does_not_open_a_browser_at_login(tmp_path):
    """Logging in should not fling a browser tab at the user."""
    AutostartCheck(Config(), home=tmp_path).fix()
    text = (tmp_path / ".config" / "autostart" / "beyondmeetings.desktop").read_text()
    assert "--no-browser" in text


def test_entry_keeps_the_global_recording_indicator_enabled(tmp_path):
    AutostartCheck(Config(), home=tmp_path).fix()
    text = (tmp_path / ".config" / "autostart" / "beyondmeetings.desktop").read_text()
    assert "--no-tray" not in text


def test_ok_once_written(tmp_path):
    check = AutostartCheck(Config(), home=tmp_path)
    check.fix()
    assert check.detect().status == "ok"


def test_autostart_is_optional(tmp_path):
    assert AutostartCheck(Config(), home=tmp_path).required is False


def test_fix_is_idempotent(tmp_path):
    check = AutostartCheck(Config(), home=tmp_path)
    check.fix()
    check.fix()
    entries = list((tmp_path / ".config" / "autostart").glob("*.desktop"))
    assert len(entries) == 1


def test_refresh_only_changes_an_entry_the_user_already_enabled(tmp_path):
    assert refresh_installed_autostart(tmp_path) is False
    AutostartCheck(Config(), home=tmp_path).fix()
    assert refresh_installed_autostart(tmp_path) is True
