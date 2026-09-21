"""What a freshly installed Windows is missing, and how to get it.

Linux and macOS have a package manager the installer can lean on. Windows does
not — or rather it has winget, which is present on current Windows 11 and
absent on plenty of Windows 10 machines, so it can be *tried* but never
required. Everything here therefore has two routes: winget when it exists, a
direct download when it does not, and a clearly reported failure when neither
works. Nothing in this module raises; a missing prerequisite is a row in a
report, never a crashed installer.

It is a Python module rather than more PowerShell for two reasons. `doctor`
needs the same "install the thing that is missing" behaviour after install
time, and one implementation means the two cannot drift. And the logic is then
unit-testable on the Linux box this project is developed on: every call that
touches the network, the registry or another process is injected.

Run directly by install.ps1 once the application is installed:

    python -m beyondmeetings.provision_windows

which prints a row per prerequisite and always exits 0.
"""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
import urllib.request
import zipfile
from dataclasses import dataclass
from pathlib import Path

from .tools import APP_DIR_NAME, which_tool

# gyan.dev is the build the ffmpeg project itself points Windows users at, and
# "release-essentials" is a stable URL rather than a versioned one, so this
# does not rot every release.
FFMPEG_URL = "https://www.gyan.dev/ffmpeg/builds/ffmpeg-release-essentials.zip"
FFMPEG_WINGET_ID = "Gyan.FFmpeg"
FFMPEG_BINARIES = ("ffmpeg.exe", "ffprobe.exe")

# The Evergreen bootstrapper. Run without elevation it performs a per-user
# install, which is what we want: installing an app must not need admin.
WEBVIEW2_URL = "https://go.microsoft.com/fwlink/p/?LinkId=2124703"
WEBVIEW2_CLIENT = "{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}"

# Some servers — gyan.dev among them — refuse a request with no User-Agent.
USER_AGENT = "beyondmeetings-installer"

DOWNLOAD_TIMEOUT = 300


@dataclass
class Outcome:
    """One prerequisite, after we have tried to satisfy it."""

    name: str
    status: str  # "ok" | "installed" | "failed" | "skipped"
    detail: str

    @property
    def satisfied(self) -> bool:
        return self.status in {"ok", "installed"}

    def line(self) -> str:
        mark = {"ok": "ok", "installed": "installed", "skipped": "skipped"}.get(
            self.status, "MISSING"
        )
        return f"  {self.name}: {mark} — {self.detail}"


def bin_dir() -> Path:
    """Where the installer keeps the binaries it fetched. Matches install.ps1."""
    override = os.environ.get("BEYONDMEETINGS_BIN")
    if override:
        return Path(override)
    local = os.environ.get("LOCALAPPDATA")
    if local:
        return Path(local) / APP_DIR_NAME / "bin"
    return Path.home() / "AppData" / "Local" / APP_DIR_NAME / "bin"


# --- the injected edges -----------------------------------------------------


def download(url: str, dest: Path) -> Path:
    """Fetch `url` to `dest`. Replaced by a fake in tests."""
    dest.parent.mkdir(parents=True, exist_ok=True)
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(request, timeout=DOWNLOAD_TIMEOUT) as response:
        with dest.open("wb") as handle:
            shutil.copyfileobj(response, handle)
    return dest


def run(args: list[str]) -> int:
    """Run a command, discarding its output. Replaced by a fake in tests."""
    flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    try:
        return subprocess.run(
            args, capture_output=True, check=False, creationflags=flags
        ).returncode
    except OSError:
        return 1


def registry_version(client: str = WEBVIEW2_CLIENT) -> str | None:
    """The installed WebView2 runtime version, or None. Windows-only."""
    try:
        import winreg
    except ImportError:  # any non-Windows machine, including this dev box
        return None

    locations = (
        (winreg.HKEY_LOCAL_MACHINE, rf"SOFTWARE\WOW6432Node\Microsoft\EdgeUpdate\Clients\{client}"),
        (winreg.HKEY_LOCAL_MACHINE, rf"SOFTWARE\Microsoft\EdgeUpdate\Clients\{client}"),
        (winreg.HKEY_CURRENT_USER, rf"SOFTWARE\Microsoft\EdgeUpdate\Clients\{client}"),
    )
    for hive, path in locations:
        try:
            with winreg.OpenKey(hive, path) as key:
                value, _ = winreg.QueryValueEx(key, "pv")
        except OSError:
            continue
        # A stub key with 0.0.0.0 means "known about, not installed".
        if value and str(value) != "0.0.0.0":
            return str(value)
    return None


# --- pure helpers, tested on any platform -----------------------------------


def extract_ffmpeg(archive: Path, dest: Path) -> list[Path]:
    """Pull just the binaries out of an ffmpeg zip, ignoring its layout.

    Builds ship as `ffmpeg-<version>-essentials_build/bin/ffmpeg.exe`, and the
    version moves. Matching on the leaf name rather than the full path means a
    new build does not silently extract nothing.
    """
    dest.mkdir(parents=True, exist_ok=True)
    written: list[Path] = []
    with zipfile.ZipFile(archive) as bundle:
        for entry in bundle.namelist():
            leaf = entry.rsplit("/", 1)[-1]
            if leaf.lower() not in FFMPEG_BINARIES:
                continue
            target = dest / leaf.lower()
            target.write_bytes(bundle.read(entry))
            target.chmod(0o755)
            written.append(target)
    return written


def winget_path(which=shutil.which) -> str | None:
    """winget ships with current Windows 11 and is absent on many Windows 10s."""
    return which("winget")


def winget_install(package: str, runner=run, which=shutil.which) -> bool:
    """Install one package silently. False when winget is absent or refuses."""
    if not winget_path(which):
        return False
    return runner([
        "winget", "install", "--id", package, "--exact", "--silent",
        "--accept-package-agreements", "--accept-source-agreements",
        "--disable-interactivity",
    ]) == 0


# --- the two prerequisites --------------------------------------------------


def ensure_ffmpeg(
    *,
    locate=which_tool,
    fetch=download,
    runner=run,
    which=shutil.which,
    dest: Path | None = None,
) -> Outcome:
    """Make ffmpeg reachable, by whatever route works."""
    found = locate("ffmpeg")
    if found:
        return Outcome("ffmpeg", "ok", found)

    if winget_install(FFMPEG_WINGET_ID, runner=runner, which=which):
        # winget puts it on PATH, but not on *this* process's PATH — the
        # environment was captured before the install. Re-reading the registry
        # is install.ps1's job; here we simply report what winget did.
        return Outcome("ffmpeg", "installed", f"winget installed {FFMPEG_WINGET_ID}")

    target = dest or bin_dir()
    with tempfile.TemporaryDirectory(prefix="bm-ffmpeg-") as scratch:
        archive = Path(scratch) / "ffmpeg.zip"
        try:
            fetch(FFMPEG_URL, archive)
            written = extract_ffmpeg(archive, target)
        except Exception as exc:  # network, DNS, proxy, a corrupt zip
            return Outcome(
                "ffmpeg",
                "failed",
                f"could not fetch {FFMPEG_URL} ({exc.__class__.__name__}: {exc}). "
                "Install it manually with: winget install Gyan.FFmpeg",
            )

    if not written:
        return Outcome(
            "ffmpeg", "failed",
            f"{FFMPEG_URL} contained no ffmpeg.exe. "
            "Install it manually with: winget install Gyan.FFmpeg",
        )
    return Outcome("ffmpeg", "installed", str(target / "ffmpeg.exe"))


def ensure_webview2(
    *,
    version=registry_version,
    fetch=download,
    runner=run,
) -> Outcome:
    """The runtime pywebview renders in. Present on Windows 11, not always on 10."""
    installed = version()
    if installed:
        return Outcome("WebView2 runtime", "ok", f"version {installed}")

    with tempfile.TemporaryDirectory(prefix="bm-webview2-") as scratch:
        setup = Path(scratch) / "MicrosoftEdgeWebview2Setup.exe"
        try:
            fetch(WEBVIEW2_URL, setup)
        except Exception as exc:
            return Outcome(
                "WebView2 runtime", "failed",
                f"could not fetch the installer ({exc.__class__.__name__}: {exc}). "
                "Get it from https://developer.microsoft.com/microsoft-edge/webview2/",
            )
        # /silent /install does a per-user install when not elevated, so this
        # never raises a UAC prompt during an ordinary install.
        code = runner([str(setup), "/silent", "/install"])

    if code != 0:
        return Outcome(
            "WebView2 runtime", "failed",
            f"the Microsoft installer exited {code}. The app window may not open; "
            "get it from https://developer.microsoft.com/microsoft-edge/webview2/",
        )
    return Outcome("WebView2 runtime", "installed", version() or "installed")


def provision(platform: str | None = None) -> list[Outcome]:
    platform = platform if platform is not None else sys.platform
    if platform != "win32":
        return [Outcome("provisioning", "skipped", f"not needed on {platform}")]
    return [ensure_ffmpeg(), ensure_webview2()]


def _use_utf8_output() -> None:
    # Same reason as cli.py's copy: a Windows console defaults to a legacy
    # code page that cannot encode the dash in a report line, and this runs
    # from install.ps1 where a traceback would read as a broken install.
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    """Always 0. A prerequisite we could not fetch is reported, not fatal —
    recording still works without WebView2 in a browser, and ffmpeg can be
    installed later with `beyondmeetings doctor`."""
    del argv
    _use_utf8_output()
    for outcome in provision():
        print(outcome.line())
    return 0


if __name__ == "__main__":  # pragma: no cover - exercised by install.ps1
    raise SystemExit(main())
