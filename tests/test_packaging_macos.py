"""The macOS capture helper's source must ship inside the wheel.

install.sh compiles bmcapture.swift out of the installed package. If hatchling
does not carry the file, a Mac install succeeds, reports a missing helper, and
cannot record — with nothing to point at. `pip install -e .` would not catch
it, which is the same trap that broke every non-editable install once before.
"""
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SWIFT = "beyondmeetings/native/bmcapture.swift"


def test_the_swift_source_is_in_the_source_tree():
    assert (ROOT / "src" / SWIFT).is_file()


def test_install_sh_builds_the_helper_from_the_installed_package():
    """Not from the repo — a curl | bash user has no checkout."""
    script = (ROOT / "install.sh").read_text(encoding="utf-8")

    assert "bmcapture.swift" in script
    assert "swiftc" in script
    assert "import beyondmeetings" in script, (
        "the helper source must be located via the installed package, not a "
        "path relative to the script"
    )


def test_install_sh_survives_a_mac_without_xcode_tools():
    """Missing swiftc must degrade, not abort — the rest of the app still works."""
    script = (ROOT / "install.sh").read_text(encoding="utf-8")

    assert "xcode-select --install" in script


@pytest.mark.skipif(shutil.which("git") is None, reason="build needs a source tree")
def test_the_wheel_carries_the_swift_source(tmp_path):
    try:
        import build  # noqa: F401
    except ImportError:
        pytest.skip("`build` not installed; run pip install build")

    result = subprocess.run(
        [sys.executable, "-m", "build", "--wheel", "--outdir", str(tmp_path)],
        cwd=ROOT, capture_output=True, text=True,
    )
    assert result.returncode == 0, result.stderr[-2000:]

    wheels = list(tmp_path.glob("*.whl"))
    assert len(wheels) == 1, wheels

    names = zipfile.ZipFile(wheels[0]).namelist()
    assert SWIFT in names, f"{SWIFT} missing from the wheel"
