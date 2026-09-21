"""which_tool must stay identical to shutil.which everywhere but Windows.

The Windows installer fetches ffmpeg into the application's own bin directory
rather than editing the user's PATH, so something has to look there. That
something must not change how Linux or macOS resolve a binary, which is what
the first two tests pin down.
"""
import sys
from pathlib import Path

from beyondmeetings.tools import app_bin_dirs, which_tool


def test_no_extra_directories_are_searched_off_windows():
    assert app_bin_dirs("linux") == []
    assert app_bin_dirs("darwin") == []


def test_off_windows_it_is_exactly_shutil_which(monkeypatch):
    monkeypatch.setattr("shutil.which", lambda name: None)
    assert which_tool("ffmpeg", platform="linux") is None

    monkeypatch.setattr("shutil.which", lambda name: "/usr/bin/ffmpeg")
    assert which_tool("ffmpeg", platform="linux") == "/usr/bin/ffmpeg"


def test_path_still_wins_on_windows(monkeypatch):
    """A machine that already has ffmpeg must keep using its own."""
    monkeypatch.setattr("shutil.which", lambda name: r"C:\tools\ffmpeg.exe")
    assert which_tool("ffmpeg", platform="win32") == r"C:\tools\ffmpeg.exe"


def test_the_app_bin_directory_is_searched_on_windows(monkeypatch, tmp_path):
    monkeypatch.setattr("shutil.which", lambda name: None)
    monkeypatch.setenv("BEYONDMEETINGS_BIN", str(tmp_path))
    (tmp_path / "ffmpeg.exe").write_bytes(b"MZ")

    assert which_tool("ffmpeg", platform="win32") == str(tmp_path / "ffmpeg.exe")


def test_missing_everywhere_is_none_on_windows(monkeypatch, tmp_path):
    monkeypatch.setattr("shutil.which", lambda name: None)
    monkeypatch.setenv("BEYONDMEETINGS_BIN", str(tmp_path))

    assert which_tool("ffmpeg", platform="win32") is None


def test_the_override_is_searched_before_the_default(monkeypatch, tmp_path):
    monkeypatch.setenv("BEYONDMEETINGS_BIN", str(tmp_path / "override"))
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "local"))

    dirs = app_bin_dirs("win32")
    assert dirs[0] == tmp_path / "override"
    assert tmp_path / "local" / "beyondMeetings" / "bin" in dirs


def test_the_venv_scripts_directory_is_always_a_candidate(monkeypatch):
    """The one location that is right even with no environment variables set."""
    monkeypatch.delenv("BEYONDMEETINGS_BIN", raising=False)
    monkeypatch.delenv("LOCALAPPDATA", raising=False)

    assert app_bin_dirs("win32") == [Path(sys.executable).parent]
