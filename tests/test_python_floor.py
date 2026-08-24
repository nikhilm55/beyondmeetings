"""The declared Python floor must match what the code can actually import.

`requires-python = ">=3.10"` while importing `tomllib` (stdlib only from 3.11)
installs cleanly on 3.10 — Ubuntu 22.04's system Python — and then dies at
first import with ModuleNotFoundError. pip cannot catch it: the metadata says
3.10 is fine. Only these checks do.
"""
import re
from pathlib import Path

try:
    import tomllib  # Python 3.11+
except ModuleNotFoundError:  # pragma: no cover - depends on interpreter
    import tomli as tomllib

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src" / "beyondmeetings"
TESTS = ROOT / "tests"


def _requires_python_floor() -> tuple[int, int]:
    with (ROOT / "pyproject.toml").open("rb") as fh:
        spec = tomllib.load(fh)["project"]["requires-python"]
    match = re.search(r">=\s*(\d+)\.(\d+)", spec)
    assert match, f"cannot read a floor out of requires-python = {spec!r}"
    return int(match.group(1)), int(match.group(2))


def _modules_importing(name: str, *roots: Path) -> list[Path]:
    return [
        path for root in (roots or (SRC,)) for path in root.rglob("*.py")
        if re.search(rf"^\s*import {name}\b", path.read_text(encoding="utf-8"), re.MULTILINE)
    ]


def test_tomllib_importers_have_a_fallback_below_311():
    """Below 3.11 `import tomllib` must fall back to the tomli backport.

    The tests are checked too: a suite that cannot run on the floor it
    claims to support is how this shipped unnoticed in the first place.
    """
    if _requires_python_floor() >= (3, 11):
        return

    missing = [
        path.relative_to(ROOT) for path in _modules_importing("tomllib", SRC, TESTS)
        if "import tomli as tomllib" not in path.read_text(encoding="utf-8")
    ]
    assert not missing, (
        f"{missing} import tomllib with no fallback, but requires-python still "
        "allows 3.10, where tomllib does not exist"
    )


def test_tomli_backport_is_declared_for_old_pythons():
    """The fallback is useless if the backport is never installed."""
    if _requires_python_floor() >= (3, 11) or not _modules_importing("tomllib"):
        return

    with (ROOT / "pyproject.toml").open("rb") as fh:
        deps = tomllib.load(fh)["project"]["dependencies"]

    tomli = [d for d in deps if re.match(r"tomli\b(?!-)", d)]
    assert tomli, f"no tomli dependency in {deps}"
    assert any(
        'python_version < "3.11"' in d for d in tomli
    ), f"tomli must carry a python_version < 3.11 marker, got {tomli}"


def test_package_imports_under_the_declared_floor():
    """Import the modules the CLI touches first — the ones that crashed."""
    from beyondmeetings import config, secrets  # noqa: F401
