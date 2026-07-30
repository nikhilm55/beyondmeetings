import shutil
import subprocess
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[1] / "install.sh"


def _run(args, env=None):
    return subprocess.run(
        ["bash", str(SCRIPT), *args], capture_output=True, text=True, env=env
    )


def test_script_exists_and_is_executable():
    assert SCRIPT.is_file()
    assert SCRIPT.stat().st_mode & 0o111


def test_script_is_syntactically_valid():
    assert subprocess.run(["bash", "-n", str(SCRIPT)]).returncode == 0


def test_script_passes_shellcheck_if_available():
    if not shutil.which("shellcheck"):
        return
    proc = subprocess.run(["shellcheck", str(SCRIPT)], capture_output=True, text=True)
    assert proc.returncode == 0, proc.stdout


def test_help_lists_the_no_uv_flag():
    assert "--no-uv" in _run(["--help"]).stdout


def test_unknown_option_is_rejected():
    assert _run(["--nonsense"]).returncode == 2


def test_dry_run_reports_the_chosen_interpreter():
    assert "python" in _run(["--dry-run"]).stdout.lower()


def test_no_uv_with_unusable_python_prints_a_distro_hint(tmp_path):
    """A Python that exists but cannot build a venv must not be accepted."""
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    for name in ("python3", "python3.10", "python3.11", "python3.12", "python3.13"):
        stub = fake_bin / name
        stub.write_text("#!/bin/sh\nexit 1\n")
        stub.chmod(0o755)
    env = {"PATH": f"{fake_bin}:/usr/bin:/bin", "HOME": str(tmp_path)}
    proc = _run(["--no-uv", "--dry-run"], env=env)
    assert proc.returncode != 0
    assert "python3-venv" in proc.stdout + proc.stderr


# --- curl | bash leaves BASH_SOURCE unset, and set -u makes that fatal ---

def test_survives_being_piped_into_bash():
    """The README's one-liner pipes this script in; BASH_SOURCE is then unset."""
    script = SCRIPT.read_text()
    proc = subprocess.run(
        ["bash", "-s", "--", "--dry-run"],
        input=script, capture_output=True, text=True,
    )
    combined = proc.stdout + proc.stderr
    assert "unbound variable" not in combined, combined
    assert proc.returncode == 0, combined


def test_bash_source_is_defaulted():
    assert "${BASH_SOURCE[0]:-}" in SCRIPT.read_text(), (
        "an undefaulted BASH_SOURCE[0] aborts under `set -u` when piped"
    )


def test_bin_dir_is_overridable():
    """Needed to sandbox-test the installer without clobbering a real install."""
    assert "BEYONDMEETINGS_BIN" in SCRIPT.read_text()


def test_installs_the_app_icon():
    assert "install_desktop_entry" in SCRIPT.read_text()
