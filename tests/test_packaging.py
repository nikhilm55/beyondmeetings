"""The wheel must build and carry its web assets.

`pip install -e .` does not build a wheel, so the dev path stayed green for
four milestones while every real install was broken: `packages` already
includes web/, and a force-include of the same directory made hatchling
reject the duplicate path. Only an actual build catches that.
"""
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
ASSETS = ("app.html", "app.css", "app.js", "setup.html", "setup.css", "setup.js")


def test_no_force_include_duplicates_the_package_dir():
    """Fast guard — the exact shape of the bug, without a build.

    Asserts on parsed TOML, not raw text: a comment explaining the bug would
    otherwise trip a substring check.
    """
    import tomllib

    with (ROOT / "pyproject.toml").open("rb") as fh:
        config = tomllib.load(fh)

    wheel = config["tool"]["hatch"]["build"]["targets"]["wheel"]
    assert wheel["packages"] == ["src/beyondmeetings"]

    forced = wheel.get("force-include", {})
    overlapping = [
        src for src in forced
        if any(src.startswith(pkg) for pkg in wheel["packages"])
    ]
    assert not overlapping, (
        f"force-include of {overlapping} duplicates paths already covered by "
        "`packages`; hatchling rejects the wheel with 'a second file is being "
        "added at the same path'"
    )


@pytest.mark.skipif(
    shutil.which("git") is None, reason="build needs a source tree"
)
def test_wheel_builds_and_contains_every_web_asset(tmp_path):
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
    for asset in ASSETS:
        assert f"beyondmeetings/web/{asset}" in names, f"{asset} missing from wheel"

    duplicates = {n for n in names if names.count(n) > 1}
    assert not duplicates, f"duplicate paths in wheel: {duplicates}"


def test_entry_point_is_declared():
    text = (ROOT / "pyproject.toml").read_text()
    assert 'beyondmeetings = "beyondmeetings.cli:main"' in text
