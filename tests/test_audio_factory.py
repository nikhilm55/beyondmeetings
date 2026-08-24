"""Backend selection per platform.

`platform` is a parameter rather than a monkeypatched sys.platform so each
branch is selected explicitly, and so a test cannot leak a patched global into
the next one.
"""
import pytest

from beyondmeetings.audio.factory import UnsupportedPlatformError, build_recorder
from beyondmeetings.audio.pipewire import PipeWireRecorder


def test_linux_gets_the_pipewire_backend(tmp_path):
    assert isinstance(build_recorder(tmp_path, platform="linux"), PipeWireRecorder)


def test_the_linux_backend_is_built_exactly_as_before(tmp_path):
    """The constraint: going through the factory must change nothing on Linux."""
    built = build_recorder(tmp_path, segment_minutes=7, platform="linux")
    direct = PipeWireRecorder(tmp_path, segment_minutes=7)

    assert built.data_dir == direct.data_dir
    assert built.segment_minutes == direct.segment_minutes
    assert built.state_path == direct.state_path


def test_macos_gets_the_mac_backend(tmp_path):
    from beyondmeetings.audio.macos import MacRecorder

    assert isinstance(build_recorder(tmp_path, platform="darwin"), MacRecorder)


def test_windows_selects_wasapi_recorder(tmp_path):
    from beyondmeetings.audio.windows import WindowsRecorder

    assert isinstance(build_recorder(tmp_path, platform="win32"), WindowsRecorder)


def test_an_unknown_platform_is_rejected_rather_than_guessed(tmp_path):
    with pytest.raises(UnsupportedPlatformError, match="plan9"):
        build_recorder(tmp_path, platform="plan9")
