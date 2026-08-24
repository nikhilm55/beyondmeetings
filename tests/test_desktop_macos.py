"""The macOS .app bundle.

The bundle is not cosmetic on macOS: TCC keys privacy grants per bundle
identifier, so without one the screen-recording and microphone grants attach to
whatever launched the process — usually Terminal — and do not carry over when
the same code is started from an app icon.

All of this is filesystem work, so it is testable here. What is not testable
without a Mac is whether macOS then attributes the grant the way we intend.
"""
import plistlib

import pytest

from beyondmeetings.desktop_macos import (
    BUNDLE_ID,
    app_bundle_path,
    helper_path,
    info_plist,
    install_app_bundle,
    remove_app_bundle,
)


def test_the_bundle_lands_in_the_users_applications_folder(tmp_path):
    assert app_bundle_path(tmp_path) == (
        tmp_path / "Applications" / "beyondMeetings.app"
    )


def test_installing_creates_the_bundle_layout(tmp_path):
    bundle = install_app_bundle(home=tmp_path)

    assert (bundle / "Contents" / "Info.plist").is_file()
    assert (bundle / "Contents" / "MacOS" / "beyondMeetings").is_file()


def test_the_launcher_is_executable(tmp_path):
    """A Contents/MacOS entry that is not executable makes the app fail to open."""
    bundle = install_app_bundle(home=tmp_path)
    launcher = bundle / "Contents" / "MacOS" / "beyondMeetings"

    assert launcher.stat().st_mode & 0o111


def test_the_plist_is_valid_and_declares_the_bundle_identifier(tmp_path):
    bundle = install_app_bundle(home=tmp_path)

    with (bundle / "Contents" / "Info.plist").open("rb") as fh:
        plist = plistlib.load(fh)

    assert plist["CFBundleIdentifier"] == BUNDLE_ID
    assert plist["CFBundleExecutable"] == "beyondMeetings"


def test_the_plist_declares_a_microphone_usage_description(tmp_path):
    """Without this key macOS kills the process outright on first mic access.

    Not "denies the request" — terminates it. It is the single most common way
    an audio app fails to launch on macOS.
    """
    bundle = install_app_bundle(home=tmp_path)

    with (bundle / "Contents" / "Info.plist").open("rb") as fh:
        plist = plistlib.load(fh)

    assert plist["NSMicrophoneUsageDescription"].strip()


def test_the_plist_declares_the_minimum_system_version(tmp_path):
    """ScreenCaptureKit audio capture is macOS 13.0+."""
    bundle = install_app_bundle(home=tmp_path)

    with (bundle / "Contents" / "Info.plist").open("rb") as fh:
        plist = plistlib.load(fh)

    assert plist["LSMinimumSystemVersion"] == "13.0"


def test_the_launcher_invokes_the_installed_command(tmp_path):
    bundle = install_app_bundle(home=tmp_path)
    launcher = (bundle / "Contents" / "MacOS" / "beyondMeetings").read_text()

    assert "beyondmeetings" in launcher
    assert " app" in launcher


def test_the_capture_helper_is_copied_into_the_bundle(tmp_path):
    """The helper must live inside the bundle to inherit its identity."""
    built = tmp_path / "built" / "bmcapture"
    built.parent.mkdir()
    built.write_text("#!/bin/sh\n")
    built.chmod(0o755)

    bundle = install_app_bundle(home=tmp_path, helper=built)

    installed = bundle / "Contents" / "MacOS" / "bmcapture"
    assert installed.is_file()
    assert installed.stat().st_mode & 0o111, "the helper must stay executable"


def test_the_helper_path_points_inside_the_bundle(tmp_path):
    assert helper_path(tmp_path) == (
        tmp_path / "Applications" / "beyondMeetings.app" / "Contents" / "MacOS"
        / "bmcapture"
    )


def test_installing_without_a_built_helper_still_produces_a_bundle(tmp_path):
    """Useful before the Swift helper is built; the app just cannot record yet."""
    bundle = install_app_bundle(home=tmp_path)

    assert bundle.is_dir()
    assert not (bundle / "Contents" / "MacOS" / "bmcapture").exists()


def test_installing_twice_is_idempotent(tmp_path):
    first = install_app_bundle(home=tmp_path)
    second = install_app_bundle(home=tmp_path)

    assert first == second
    assert (second / "Contents" / "Info.plist").is_file()


def test_removing_deletes_the_whole_bundle(tmp_path):
    bundle = install_app_bundle(home=tmp_path)
    remove_app_bundle(home=tmp_path)

    assert not bundle.exists()


def test_removing_a_bundle_that_is_not_there_is_not_an_error(tmp_path):
    remove_app_bundle(home=tmp_path)


def test_info_plist_is_serialisable_without_touching_the_disk():
    """The plist content is pure data, so it can be checked in isolation."""
    plist = plistlib.loads(plistlib.dumps(info_plist()))

    assert plist["CFBundleName"] == "beyondMeetings"
    assert plist["CFBundlePackageType"] == "APPL"


@pytest.mark.parametrize(
    "key",
    [
        "CFBundleIdentifier",
        "CFBundleExecutable",
        "CFBundleName",
        "CFBundlePackageType",
        "CFBundleShortVersionString",
        "LSMinimumSystemVersion",
        "NSMicrophoneUsageDescription",
    ],
)
def test_every_key_the_bundle_needs_is_present(key):
    assert key in info_plist()
