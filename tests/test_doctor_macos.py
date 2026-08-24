"""macOS checks, and the platform-conditional registry that shows them.

The checks themselves are filesystem and subprocess work, so they run here.
What cannot be verified without a Mac is whether the permissions they report
mean what we think they mean.
"""
import sys

import pytest

from beyondmeetings.config import Config
from beyondmeetings.doctor.macos import (
    AppBundleCheck,
    CaptureHelperCheck,
    MicrophonePermissionCheck,
    ScreenRecordingPermissionCheck,
)
from beyondmeetings.doctor.registry import build_checks

# The permission checks execute a shell-script stand-in for bmcapture, which
# Windows cannot run ("%1 is not a valid Win32 application"). The condition
# fires only on win32, so Linux and macOS runs are unchanged.
pytestmark = pytest.mark.skipif(
    sys.platform == "win32", reason="these checks execute a shell helper; macOS-only"
)


def _fake_helper(tmp_path, payload):
    """A stand-in bmcapture that prints the permission JSON we want to test."""
    helper = (
        tmp_path / "Applications" / "beyondMeetings.app" / "Contents" / "MacOS"
        / "bmcapture"
    )
    helper.parent.mkdir(parents=True, exist_ok=True)
    helper.write_text(f"#!/bin/sh\ncat <<'JSON'\n{payload}\nJSON\n")
    helper.chmod(0o755)
    return helper


# --- capture helper ---

def test_the_helper_check_is_missing_before_it_is_built(tmp_path):
    result = CaptureHelperCheck(home=tmp_path).detect()

    assert result.status == "missing"
    assert "installer" in result.detail


def test_the_helper_check_passes_once_it_exists(tmp_path):
    _fake_helper(tmp_path, "{}")

    assert CaptureHelperCheck(home=tmp_path).detect().status == "ok"


# --- app bundle ---

def test_the_bundle_check_is_missing_before_installation(tmp_path):
    assert AppBundleCheck(home=tmp_path).detect().status == "missing"


def test_the_bundle_check_can_fix_itself(tmp_path):
    check = AppBundleCheck(home=tmp_path)
    assert check.fixable

    result = check.fix()

    assert result.status == "ok"


# --- permissions ---

def test_screen_recording_reports_granted(tmp_path):
    _fake_helper(tmp_path, '{"screen_recording": true, "microphone": true}')

    assert ScreenRecordingPermissionCheck(home=tmp_path).detect().status == "ok"


def test_screen_recording_reports_denied_with_a_route_to_the_setting(tmp_path):
    _fake_helper(tmp_path, '{"screen_recording": false, "microphone": true}')

    result = ScreenRecordingPermissionCheck(home=tmp_path).detect()

    assert result.status == "missing"
    assert "Privacy_ScreenCapture" in result.detail


def test_screen_recording_says_a_relaunch_is_needed(tmp_path):
    """Granting it changes nothing until the app restarts; users assume it broke."""
    _fake_helper(tmp_path, '{"screen_recording": false, "microphone": true}')

    detail = ScreenRecordingPermissionCheck(home=tmp_path).detect().detail

    assert "reopened" in detail


def test_the_microphone_is_optional_because_capture_still_works_without_it(tmp_path):
    _fake_helper(tmp_path, '{"screen_recording": true, "microphone": false}')
    check = MicrophonePermissionCheck(home=tmp_path)

    result = check.detect()

    assert check.required is False
    assert result.status == "missing"
    assert "own voice" in result.detail


def test_permissions_degrade_gracefully_when_the_helper_is_absent(tmp_path):
    result = ScreenRecordingPermissionCheck(home=tmp_path).detect()

    assert result.status == "missing"
    assert "not built" in result.detail


def test_a_helper_returning_junk_does_not_crash_the_wizard(tmp_path):
    """A check that raises takes the whole setup page down with it."""
    _fake_helper(tmp_path, "not json at all")

    assert ScreenRecordingPermissionCheck(home=tmp_path).detect().status == "missing"


# --- registry dispatch ---

def test_linux_sees_pipewire_and_no_macos_checks():
    ids = {c.id for c in build_checks(Config(), platform="linux")}

    assert "pipewire" in ids
    assert not {"capture-helper", "app-bundle", "screen-recording"} & ids


def test_macos_sees_its_own_checks_and_not_pipewire():
    ids = {c.id for c in build_checks(Config(), platform="darwin")}

    assert "pipewire" not in ids
    assert {"xcode-tools", "capture-helper", "app-bundle", "screen-recording"} <= ids


def test_both_platforms_still_need_ffmpeg():
    for platform in ("linux", "darwin"):
        ids = {c.id for c in build_checks(Config(), platform=platform)}
        assert "ffmpeg" in ids, platform


def test_the_linux_launcher_check_is_not_offered_on_macos():
    """The freedesktop .desktop entry means nothing on a Mac."""
    ids = {c.id for c in build_checks(Config(), platform="darwin")}

    assert "launcher" not in ids
