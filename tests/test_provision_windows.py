"""Fetching what a bare Windows is missing.

Every edge — the network, winget, the registry, the Microsoft installer — is
injected, so the whole module is exercised on the Linux box this project is
developed on rather than only on a Windows machine nobody has to hand.

The single most important property here is that nothing raises. This code runs
at the end of an installation that has already succeeded; a prerequisite it
cannot fetch has to come back as a reported row, never as an exception that
turns a working install into a failed one.
"""
import zipfile
from pathlib import Path

from beyondmeetings.provision_windows import (
    FFMPEG_URL,
    Outcome,
    bin_dir,
    ensure_ffmpeg,
    ensure_webview2,
    extract_ffmpeg,
    main,
    provision,
    winget_install,
)


def _ffmpeg_zip(path: Path, prefix: str = "ffmpeg-7.1-essentials_build") -> Path:
    with zipfile.ZipFile(path, "w") as bundle:
        bundle.writestr(f"{prefix}/README.txt", "docs")
        bundle.writestr(f"{prefix}/bin/ffmpeg.exe", "MZ-ffmpeg")
        bundle.writestr(f"{prefix}/bin/ffprobe.exe", "MZ-ffprobe")
        bundle.writestr(f"{prefix}/bin/ffplay.exe", "MZ-ffplay")
    return path


# --- pulling the binaries out of a build ------------------------------------


def test_extracts_the_two_binaries_it_needs(tmp_path):
    archive = _ffmpeg_zip(tmp_path / "ffmpeg.zip")
    dest = tmp_path / "bin"

    written = extract_ffmpeg(archive, dest)

    assert sorted(p.name for p in written) == ["ffmpeg.exe", "ffprobe.exe"]
    assert (dest / "ffmpeg.exe").read_bytes() == b"MZ-ffmpeg"


def test_it_leaves_the_rest_of_the_build_behind(tmp_path):
    archive = _ffmpeg_zip(tmp_path / "ffmpeg.zip")
    dest = tmp_path / "bin"

    extract_ffmpeg(archive, dest)

    assert not (dest / "ffplay.exe").exists()
    assert not (dest / "README.txt").exists()


def test_a_new_build_version_does_not_break_extraction(tmp_path):
    """The top-level folder carries the version, so matching it would rot."""
    archive = _ffmpeg_zip(tmp_path / "f.zip", prefix="ffmpeg-99.0-essentials_build")

    written = extract_ffmpeg(archive, tmp_path / "bin")

    assert len(written) == 2


# --- ffmpeg, by whichever route works ---------------------------------------


def test_an_ffmpeg_already_on_the_machine_is_left_alone(tmp_path):
    def fetch(url, dest):
        raise AssertionError("must not download when ffmpeg is already present")

    outcome = ensure_ffmpeg(
        locate=lambda name: r"C:\tools\ffmpeg.exe",
        fetch=fetch,
        which=lambda name: None,
        dest=tmp_path,
    )

    assert outcome.status == "ok"
    assert outcome.satisfied


def test_winget_is_tried_before_downloading(tmp_path):
    calls = []

    outcome = ensure_ffmpeg(
        locate=lambda name: None,
        fetch=lambda url, dest: (_ for _ in ()).throw(AssertionError("downloaded")),
        runner=lambda args: calls.append(args) or 0,
        which=lambda name: "winget",
        dest=tmp_path,
    )

    assert outcome.status == "installed"
    assert calls and calls[0][:2] == ["winget", "install"]


def test_it_downloads_when_winget_is_absent(tmp_path):
    def fetch(url, dest):
        assert url == FFMPEG_URL
        _ffmpeg_zip(Path(dest))

    outcome = ensure_ffmpeg(
        locate=lambda name: None,
        fetch=fetch,
        runner=lambda args: 1,
        which=lambda name: None,
        dest=tmp_path,
    )

    assert outcome.status == "installed"
    assert (tmp_path / "ffmpeg.exe").is_file()


def test_it_downloads_when_winget_refuses(tmp_path):
    """winget exists but the package source is unreachable or blocked."""
    def fetch(url, dest):
        _ffmpeg_zip(Path(dest))

    outcome = ensure_ffmpeg(
        locate=lambda name: None,
        fetch=fetch,
        runner=lambda args: 1,
        which=lambda name: "winget",
        dest=tmp_path,
    )

    assert outcome.status == "installed"


def test_a_failed_download_is_reported_not_raised(tmp_path):
    def fetch(url, dest):
        raise OSError("getaddrinfo failed")

    outcome = ensure_ffmpeg(
        locate=lambda name: None,
        fetch=fetch,
        runner=lambda args: 1,
        which=lambda name: None,
        dest=tmp_path,
    )

    assert outcome.status == "failed"
    assert not outcome.satisfied
    assert "winget install Gyan.FFmpeg" in outcome.detail


def test_an_archive_without_ffmpeg_is_reported_not_raised(tmp_path):
    def fetch(url, dest):
        with zipfile.ZipFile(dest, "w") as bundle:
            bundle.writestr("something/else.txt", "nope")

    outcome = ensure_ffmpeg(
        locate=lambda name: None,
        fetch=fetch,
        runner=lambda args: 1,
        which=lambda name: None,
        dest=tmp_path,
    )

    assert outcome.status == "failed"


def test_winget_install_is_silent_and_non_interactive():
    """An installer that stops for a licence prompt hangs a one-line install."""
    seen = []
    winget_install("Gyan.FFmpeg", runner=lambda a: seen.append(a) or 0,
                   which=lambda n: "winget")

    assert "--silent" in seen[0]
    assert "--accept-package-agreements" in seen[0]
    assert "--disable-interactivity" in seen[0]


def test_winget_install_says_no_when_winget_is_missing():
    assert winget_install("X", runner=lambda a: 0, which=lambda n: None) is False


# --- the WebView2 runtime ---------------------------------------------------


def test_an_installed_runtime_is_left_alone():
    outcome = ensure_webview2(
        version=lambda: "121.0.2277.128",
        fetch=lambda url, dest: (_ for _ in ()).throw(AssertionError("downloaded")),
    )

    assert outcome.status == "ok"
    assert "121" in outcome.detail


def test_a_missing_runtime_is_fetched_and_installed_per_user():
    seen = []
    versions = iter([None, "121.0.2277.128"])

    outcome = ensure_webview2(
        version=lambda: next(versions),
        fetch=lambda url, dest: Path(dest).write_bytes(b"MZ"),
        runner=lambda args: seen.append(args) or 0,
    )

    assert outcome.status == "installed"
    # /silent /install, unelevated, is a per-user install: no UAC prompt.
    assert seen[0][1:] == ["/silent", "/install"]


def test_a_failed_runtime_install_is_reported_not_raised():
    outcome = ensure_webview2(
        version=lambda: None,
        fetch=lambda url, dest: Path(dest).write_bytes(b"MZ"),
        runner=lambda args: 3,
    )

    assert outcome.status == "failed"
    assert "webview2" in outcome.detail.lower()


def test_an_unreachable_runtime_download_is_reported_not_raised():
    outcome = ensure_webview2(
        version=lambda: None,
        fetch=lambda url, dest: (_ for _ in ()).throw(TimeoutError("timed out")),
        runner=lambda args: 0,
    )

    assert outcome.status == "failed"


# --- the entry point install.ps1 calls --------------------------------------


def test_provisioning_is_a_no_op_off_windows():
    outcomes = provision(platform="linux")

    assert [o.status for o in outcomes] == ["skipped"]


def test_the_entry_point_always_exits_zero(capsys, monkeypatch):
    """It runs after a successful install; it must never fail that install.

    `provision` is replaced rather than left to run: on the Windows CI runner
    the real one would download ffmpeg, and a test suite must not pull 80 MB
    off the internet.
    """
    monkeypatch.setattr(
        "beyondmeetings.provision_windows.provision",
        lambda: [Outcome("ffmpeg", "failed", "no network at all")],
    )

    assert main([]) == 0
    assert "no network at all" in capsys.readouterr().out


def test_the_report_is_printed_as_utf8(monkeypatch):
    """A report line carries an em dash. A Windows console defaults to a code
    page that cannot encode it, and this runs from install.ps1, where a
    traceback would read as a broken install."""
    class Stream:
        def __init__(self):
            self.encodings = []

        def reconfigure(self, encoding=None):
            self.encodings.append(encoding)

        def write(self, text):
            return len(text)

        def flush(self):
            pass

    stream = Stream()
    monkeypatch.setattr("sys.stdout", stream)
    monkeypatch.setattr("sys.stderr", stream)
    monkeypatch.setattr(
        "beyondmeetings.provision_windows.provision",
        lambda: [Outcome("ffmpeg", "ok", "somewhere")],
    )

    main([])

    assert "utf-8" in stream.encodings


def test_printing_survives_a_stream_that_cannot_reconfigure(monkeypatch, capsys):
    """capsys' replacement has no reconfigure, and neither does a pipe on
    some platforms. Missing it must not raise."""
    monkeypatch.setattr(
        "beyondmeetings.provision_windows.provision",
        lambda: [Outcome("ffmpeg", "ok", "somewhere")],
    )

    assert main([]) == 0


def test_a_failed_row_reads_as_missing():
    assert "MISSING" in Outcome("ffmpeg", "failed", "no network").line()


def test_the_bin_directory_matches_the_installers(monkeypatch, tmp_path):
    monkeypatch.delenv("BEYONDMEETINGS_BIN", raising=False)
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))

    assert bin_dir() == tmp_path / "beyondMeetings" / "bin"


def test_the_bin_directory_honours_the_override(monkeypatch, tmp_path):
    monkeypatch.setenv("BEYONDMEETINGS_BIN", str(tmp_path / "elsewhere"))

    assert bin_dir() == tmp_path / "elsewhere"
