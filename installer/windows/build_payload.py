"""Assemble everything beyondMeetings-Setup-x64.exe carries.

The one-line installer fetches its prerequisites at install time. That is the
right trade for a developer machine and the wrong one for the person this
setup.exe exists for: someone who has PowerShell, a browser and nothing else,
possibly behind a proxy that eats raw GitHub. So the whole dependency tree —
a CPython runtime, every wheel, ffmpeg — is downloaded *here*, on a build
machine, and shipped inside the installer. Installing then touches the
network zero times.

Three things are fetched:

* CPython, as an `install_only` build from astral-sh/python-build-standalone.
  These are relocatable full interpreters (the same ones `uv` hands out), so
  they can be copied into %LOCALAPPDATA% and used from there. The exact asset
  is resolved from the GitHub release API rather than pinned, because a
  hardcoded tag rots the moment upstream cuts a release and the failure
  surfaces as a 404 in CI months later.
* Every wheel, produced by `pip wheel` run with *that* interpreter, so the
  binary wheels match the interpreter that will import them.
* ffmpeg, through the same URL and the same extraction code the application
  uses at runtime, so the two cannot drift.

Run it on Windows: `pip wheel` picks wheels for the platform it runs on, and
a Linux build would quietly bundle manylinux wheels that cannot be imported.
Everything except that step is unit-tested on Linux.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import tarfile
import tempfile
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

from beyondmeetings.provision_windows import (  # noqa: E402  (needs the path above)
    FFMPEG_URL,
    USER_AGENT,
    download,
    extract_ffmpeg,
)

# 3.12 rather than the newest release: every dependency publishes wheels for
# it, so `pip wheel` never falls back to building from source and needing a
# compiler on the build machine.
PYTHON_SERIES = "3.12"
PYTHON_TRIPLE = "x86_64-pc-windows-msvc"

# `install_only` is the plain relocatable layout — python.exe at the root,
# Lib\site-packages beside it. The other flavours are debug/PGO build trees
# that are several times the size and need unpacking rules of their own.
PYTHON_FLAVOUR = "install_only.tar.gz"

PYTHON_RELEASE_API = (
    "https://api.github.com/repos/astral-sh/python-build-standalone/releases/latest"
)

# Not [desktop]: the Windows app is used in a browser, so pywebview and the
# WebView2 runtime it needs are dead weight here. [tray] is what remains —
# the notification-area icon, which is the one piece of native UI that is
# still worth having.
EXTRAS = "tray"

API_TIMEOUT = 60


# --- choosing the interpreter ------------------------------------------------


def select_python_asset(
    names,
    series: str = PYTHON_SERIES,
    triple: str = PYTHON_TRIPLE,
    flavour: str = PYTHON_FLAVOUR,
) -> str:
    """The newest matching asset name in a release.

    One release carries several patch versions of several series for a dozen
    targets, so this filters hard and then takes the highest (patch, build
    date). Matching is anchored at both ends: `install_only.tar.gz` is a
    suffix of nothing else, but `install_only_stripped.tar.gz` would match a
    sloppy `in` test and ship an interpreter with no standard library symbols.
    """
    pattern = re.compile(
        rf"^cpython-{re.escape(series)}\.(\d+)\+(\d+)-"
        rf"{re.escape(triple)}-{re.escape(flavour)}$"
    )
    best: tuple[tuple[int, int], str] | None = None
    for name in names:
        found = pattern.match(name)
        if not found:
            continue
        key = (int(found.group(1)), int(found.group(2)))
        if best is None or key > best[0]:
            best = (key, name)
    if best is None:
        raise LookupError(
            f"no cpython-{series}.x {triple} {flavour} asset in that release"
        )
    return best[1]


def resolve_python_url(release: dict, **kwargs) -> str:
    assets = release.get("assets") or []
    wanted = select_python_asset([a.get("name", "") for a in assets], **kwargs)
    for asset in assets:
        if asset.get("name") == wanted:
            url = asset.get("browser_download_url")
            if url:
                return url
    raise LookupError(f"{wanted} has no download URL")


def api_headers(environ=None) -> dict[str, str]:
    """Headers for the release lookup, authenticated when we can be.

    GitHub allows 60 anonymous API calls an hour *per IP*, and CI runners
    share addresses — two builds of the same push were enough to get a
    `403: rate limit exceeded`, which failed a job that had nothing wrong
    with it. A token raises the limit to 5000, and every workflow already
    has one.
    """
    environ = os.environ if environ is None else environ
    headers = {"User-Agent": USER_AGENT, "Accept": "application/vnd.github+json"}
    token = environ.get("GITHUB_TOKEN") or environ.get("GH_TOKEN")
    if token:
        headers["Authorization"] = f"Bearer {token}"
    return headers


def read_json(url: str) -> dict:
    """Fetch and parse JSON. Replaced by a fake in tests."""
    request = urllib.request.Request(url, headers=api_headers())
    with urllib.request.urlopen(request, timeout=API_TIMEOUT) as response:
        return json.loads(response.read().decode("utf-8"))


# --- unpacking ----------------------------------------------------------------


def unpack_python(archive: Path, dest: Path) -> Path:
    """Extract an install_only build so that `dest/python.exe` is the runtime.

    The archive wraps everything in a single `python/` directory. Flattening
    it here rather than in the .iss keeps the installed layout described in
    one place.
    """
    if dest.exists():
        shutil.rmtree(dest)
    with tempfile.TemporaryDirectory(prefix="bm-python-") as scratch:
        with tarfile.open(archive, "r:gz") as bundle:
            # `data` refuses absolute paths, parent traversal and device
            # files. It is the default from 3.14 and a warning before that.
            try:
                bundle.extractall(scratch, filter="data")
            except TypeError:  # pragma: no cover - Python < 3.11.4
                bundle.extractall(scratch)
        roots = [p for p in Path(scratch).iterdir() if p.is_dir()]
        if len(roots) != 1:
            raise RuntimeError(
                f"expected one top-level directory in {archive.name}, "
                f"found {[p.name for p in roots]}"
            )
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(roots[0]), str(dest))
    return dest


def python_executable(runtime: Path) -> Path:
    return runtime / "python.exe"


# --- the three payload pieces --------------------------------------------------


def fetch_python(
    dest: Path,
    url: str | None = None,
    fetch=download,
    api=read_json,
    unpack=unpack_python,
    **kwargs,
) -> Path:
    if url is None:
        url = resolve_python_url(api(PYTHON_RELEASE_API), **kwargs)
    with tempfile.TemporaryDirectory(prefix="bm-runtime-") as scratch:
        archive = Path(scratch) / "python.tar.gz"
        fetch(url, archive)
        unpack(archive, dest)
    return dest


def upgrade_pip(python_exe: Path, runner=subprocess.run) -> None:
    """Bring the shipped interpreter's pip up to date before wheeling.

    An install_only build carries whatever pip was current when it was cut.
    That pip is also the one `python -m venv` seeds into the user's
    environment, so it is worth replacing here rather than discovering on
    someone's machine that it cannot read a dependency's metadata. A failure
    is not fatal: the bundled pip usually works, and the wheel build below
    will say so plainly if it does not.
    """
    runner(
        [str(python_exe), "-m", "pip", "install", "--upgrade",
         "--disable-pip-version-check", "pip", "setuptools", "wheel"],
        check=False,
    )


def collect_wheels(
    python_exe: Path,
    dest: Path,
    project: Path = ROOT,
    extras: str = EXTRAS,
    runner=subprocess.run,
) -> Path:
    """Build a wheel for the project and download one for every dependency.

    `pip wheel` rather than `pip download`: the project itself is a source
    tree, and only `wheel` will build it *and* resolve its dependencies in
    the same pass.
    """
    dest.mkdir(parents=True, exist_ok=True)
    completed = runner(
        [
            str(python_exe), "-m", "pip", "wheel",
            "--wheel-dir", str(dest),
            "--no-cache-dir",
            f"{project}[{extras}]",
        ],
        check=False,
    )
    if completed.returncode != 0:
        raise RuntimeError(f"pip wheel exited {completed.returncode}")
    return dest


def fetch_ffmpeg(dest: Path, fetch=download, extract=extract_ffmpeg) -> list[Path]:
    """The same URL and the same extraction the application uses at runtime."""
    with tempfile.TemporaryDirectory(prefix="bm-ffmpeg-") as scratch:
        archive = Path(scratch) / "ffmpeg.zip"
        fetch(FFMPEG_URL, archive)
        written = extract(archive, dest)
    if not written:
        raise RuntimeError(f"{FFMPEG_URL} contained no ffmpeg.exe")
    return written


# --- putting it together -------------------------------------------------------


def build(
    out: Path,
    python_url: str | None = None,
    project: Path = ROOT,
    extras: str = EXTRAS,
    report=print,
) -> Path:
    out = Path(out)
    runtime = out / "runtime"
    wheels = out / "wheels"
    binaries = out / "bin"

    report(f"CPython {PYTHON_SERIES} ({PYTHON_TRIPLE}) -> {runtime}")
    fetch_python(runtime, url=python_url)

    report(f"wheels for .[{extras}] -> {wheels}")
    upgrade_pip(python_executable(runtime))
    collect_wheels(python_executable(runtime), wheels, project=project, extras=extras)

    report(f"ffmpeg -> {binaries}")
    fetch_ffmpeg(binaries)

    report(f"payload ready: {out}")
    return out


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--out", type=Path, default=ROOT / "build" / "windows" / "payload",
        help="where to assemble the payload",
    )
    parser.add_argument(
        "--python-url",
        help="skip the release lookup and take this install_only tarball",
    )
    parser.add_argument("--extras", default=EXTRAS)
    args = parser.parse_args(argv)

    build(args.out, python_url=args.python_url, extras=args.extras)
    return 0


if __name__ == "__main__":  # pragma: no cover - exercised by the workflow
    raise SystemExit(main())
