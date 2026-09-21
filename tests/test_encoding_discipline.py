"""Every text file operation must name its encoding.

Python uses the platform's preferred encoding when you omit it, which is UTF-8
on Linux and cp1252 on Windows. That difference cost a whole CI round: the Home
template contains "←", `vault/scaffold.py` wrote it without an encoding, and
Windows died with

    UnicodeEncodeError: 'charmap' codec can't encode character '\\u2190'

before any recording could happen. Reviewing diffs does not catch this — the
call looks perfectly fine — so it is asserted instead.

This runs on every platform, which is the point: the bug is invisible on Linux,
so a Linux-only guard is what is needed to stop it reaching Windows again.
"""
import ast
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
TEXT_CALLS = {"write_text", "read_text", "open"}


def _label(path: Path) -> str:
    """Repo-relative where possible. The self-tests below feed it a tmp_path
    sample, which is not under ROOT at all, and relative_to() raises on that."""
    try:
        return str(path.relative_to(ROOT))
    except ValueError:
        return str(path)


def _offenders(path: Path) -> list[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    found = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        if isinstance(func, ast.Attribute):
            name = func.attr
        elif isinstance(func, ast.Name):
            name = func.id
        else:
            continue
        if name not in TEXT_CALLS:
            continue

        # os.open takes an int flag and a mode, never an encoding.
        # tarfile.open returns an archive, and its `encoding` argument names
        # the charset of the *member names* inside it — passing "utf-8" there
        # would say something true but unrelated, and the payload is binary.
        if (
            isinstance(func, ast.Attribute)
            and isinstance(func.value, ast.Name)
            and func.value.id in {"os", "tarfile"}
        ):
            continue

        # Binary mode has no encoding to give.
        if name == "open" and any(
            isinstance(arg, ast.Constant)
            and isinstance(arg.value, str)
            and "b" in arg.value
            for arg in node.args
        ):
            continue

        if not any(kw.arg == "encoding" for kw in node.keywords):
            found.append(f"{_label(path)}:{node.lineno} .{name}()")
    return found


def _python_files(folder: str) -> list[Path]:
    return sorted((ROOT / folder).rglob("*.py"))


@pytest.mark.parametrize("folder", ["src", "tests"])
def test_no_text_io_relies_on_the_platform_encoding(folder):
    offenders = [line for path in _python_files(folder) for line in _offenders(path)]
    assert not offenders, (
        "These calls would use cp1252 on Windows. Pass encoding=\"utf-8\":\n  "
        + "\n  ".join(offenders)
    )


def test_the_guard_actually_detects_a_bare_call(tmp_path):
    """A test that cannot fail is worse than no test."""
    sample = tmp_path / "sample.py"
    sample.write_text(
        "from pathlib import Path\nPath('x').write_text('hi')\n", encoding="utf-8"
    )

    assert _offenders(sample), "the AST walk stopped detecting bare calls"


def test_the_guard_accepts_an_explicit_encoding(tmp_path):
    sample = tmp_path / "sample.py"
    sample.write_text(
        "from pathlib import Path\n"
        "Path('x').write_text('hi', encoding='utf-8')\n",
        encoding="utf-8",
    )

    assert not _offenders(sample)


def test_the_guard_ignores_binary_and_fd_level_calls(tmp_path):
    sample = tmp_path / "sample.py"
    sample.write_text(
        "import os\n"
        "import tarfile\n"
        "open('x', 'rb')\n"
        "os.open('x', os.O_RDONLY)\n"
        "tarfile.open('x.tar.gz', 'r:gz')\n",
        encoding="utf-8",
    )

    assert not _offenders(sample)


def test_the_exemptions_are_scoped_to_those_modules(tmp_path):
    """`os` and `tarfile` are exempt; a variable that happens to be called
    something else is not, or the guard could be switched off by renaming."""
    sample = tmp_path / "sample.py"
    sample.write_text("zipfile.open('x')\n", encoding="utf-8")

    assert _offenders(sample)
