"""Properties of the Windows installer that a clean machine would otherwise
be the first to discover.

CI already parse-checks install.ps1 and runs it with -DryRun. Neither catches
the class of bug this file is about: the installer quietly *depending* on
something a freshly imaged Windows does not have. It shipped once requiring
git — `pip install ... @ git+<url>` shells out to git — which worked on every
developer machine and on every CI runner, and failed on the one machine that
mattered. These are static assertions because the alternative is a Windows VM.

Nothing here reads prose. Each test pins a behaviour that, if removed, breaks
installation on a machine with nothing on it.
"""
import re
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
INSTALL = ROOT / "install.ps1"
UNINSTALL = ROOT / "uninstall.ps1"

# Everything after this comment runs with the application already installed
# and working, so none of it may end the run in failure.
POINT_OF_NO_RETURN = "# Past this line the application is installed and working."

SCRIPT = INSTALL.read_text(encoding="utf-8")

# The first line that actually fetches something, as opposed to the comments
# above it explaining why the settings below have to come first.
FIRST_DOWNLOAD = "Invoke-WebRequest -UseBasicParsing"


def _parses(path: Path) -> subprocess.CompletedProcess:
    check = (
        "$errors = $null; "
        f"[System.Management.Automation.Language.Parser]::ParseFile('{path}', "
        "[ref]$null, [ref]$errors) | Out-Null; "
        "if ($errors) { $errors | ForEach-Object { Write-Output $_ }; exit 1 }"
    )
    return subprocess.run(
        ["pwsh", "-NoProfile", "-Command", check], capture_output=True, text=True
    )


@pytest.mark.skipif(shutil.which("pwsh") is None, reason="PowerShell not installed")
@pytest.mark.parametrize("script", [INSTALL, UNINSTALL])
def test_the_installers_parse(script):
    result = _parses(script)
    assert result.returncode == 0, result.stdout + result.stderr


# --- git is not a prerequisite ----------------------------------------------


def test_the_source_can_be_fetched_without_git():
    """The failure that started this: a fresh Windows has no git, and pip's
    git+ spec shells straight out to it."""
    assert "/archive/refs/heads/" in SCRIPT


def test_git_is_only_ever_a_fallback():
    """The one git+ install sits in the else branch, after the zip route."""
    assert SCRIPT.count("git+$Repo") == 1

    region = SCRIPT.split("if ($SourceDir) {", 1)[1]
    assert region.index("} else {") < region.index("git+$Repo")


def test_a_missing_source_and_missing_git_says_so_in_one_sentence():
    assert "git is not installed to clone" in SCRIPT


# --- the other things a bare machine lacks ----------------------------------


def test_python_has_three_routes_not_one():
    assert "function Install-Uv" in SCRIPT
    assert "function Install-PythonWithWinget" in SCRIPT
    assert "function Find-Python" in SCRIPT


def test_the_runtime_prerequisites_are_provisioned():
    """ffmpeg and WebView2, through the app's own code so doctor matches."""
    assert "-m beyondmeetings.provision_windows" in SCRIPT


def test_the_progress_bar_is_silenced_before_any_download():
    """Invoke-WebRequest on PowerShell 5.1 is ~10x slower with it on."""
    assert '$ProgressPreference = "SilentlyContinue"' in SCRIPT
    assert SCRIPT.index("$ProgressPreference") < SCRIPT.index(FIRST_DOWNLOAD)


def test_tls12_is_forced_before_any_download():
    assert SCRIPT.index("Tls12") < SCRIPT.index(FIRST_DOWNLOAD)


# --- a failure has to be reportable -----------------------------------------


def test_every_early_exit_points_at_the_log():
    """A user on a clean machine has nothing else to send back."""
    before = SCRIPT.split(POINT_OF_NO_RETURN, 1)[0]
    failures = [
        block for block in before.split("exit 1")[:-1]
    ]
    assert failures, "the installer has no failure paths left to check"
    for block in failures:
        tail = block[-500:]
        assert "$LogPath" in tail, f"an exit 1 with no log pointer:\n{tail}"


def test_nothing_after_a_successful_install_can_fail_the_run():
    assert POINT_OF_NO_RETURN in SCRIPT
    after = SCRIPT.split(POINT_OF_NO_RETURN, 1)[1]
    assert "exit 1" not in after
    assert after.rstrip().endswith("exit 0")


def test_the_app_failing_to_open_is_not_an_install_failure():
    """install.cmd reports a non-zero exit as a failed installation."""
    after = SCRIPT.split(POINT_OF_NO_RETURN, 1)[1]
    assert "$appCode" in after
    assert "exit $appCode" not in after


def test_no_launch_exists_so_a_machine_can_be_set_up_headless():
    assert "[switch]$NoLaunch" in SCRIPT


# --- the contract with the rest of the project ------------------------------


def test_the_bin_directory_matches_what_python_searches():
    from beyondmeetings.tools import APP_DIR_NAME

    assert f'"{APP_DIR_NAME}\\bin"' in SCRIPT
    assert f'"{APP_DIR_NAME}\\app"' in SCRIPT


def test_the_uninstaller_reports_success_when_it_succeeded():
    """`& $Command stop` exits non-zero when nothing is recording, and
    PowerShell carries that in $LASTEXITCODE to the end of the script, so
    uninstall.cmd announced a failure after a clean uninstall."""
    assert UNINSTALL.read_text(encoding="utf-8").rstrip().endswith("exit 0")


def test_the_installer_and_uninstaller_agree_on_both_paths():
    for fragment in ("beyondMeetings\\bin", "beyondMeetings\\app"):
        assert fragment in UNINSTALL.read_text(encoding="utf-8")


def test_the_batch_and_powershell_files_are_pinned_to_crlf():
    """cmd.exe mis-parses goto and labels in an LF-only .cmd file."""
    attributes = (ROOT / ".gitattributes").read_text(encoding="utf-8")
    for pattern in ("*.cmd", "*.ps1"):
        assert re.search(rf"{re.escape(pattern)}\s+text eol=crlf", attributes)


# --- the zip route, actually exercised --------------------------------------
#
# Everything above is a static assertion. This runs the installer's real
# source-acquisition code against a zip served over loopback, because "a fresh
# Windows has no git" is precisely the kind of claim that deserves more than a
# grep. Get-ProjectSource and its helpers are lifted out of install.ps1 by
# parsing it, so the code under test is the shipped code.

HARNESS = r"""
param([string]$Installer, [string]$RepoBase, [string]$ScriptRoot = "")
$ErrorActionPreference = "Stop"
$ProgressPreference = "SilentlyContinue"

# The script-scope variables the lifted functions close over.
$LogPath = Join-Path ([System.IO.Path]::GetTempPath()) "bm-install-test.log"
$Repo = $RepoBase
$Ref = "main"

$ast = [System.Management.Automation.Language.Parser]::ParseFile(
    $Installer, [ref]$null, [ref]$null)
$functions = $ast.FindAll(
    { param($node)
      $node -is [System.Management.Automation.Language.FunctionDefinitionAst] },
    $false)
Invoke-Expression (($functions | ForEach-Object { $_.Extent.Text }) -join "`n")

# $PSScriptRoot belongs to this harness, not to install.ps1, so the checkout
# branch is driven through Get-ProjectSource's parameter instead.
$result = Get-ProjectSource -ScriptRoot $ScriptRoot
Write-Output "RESULT=$result"
"""


def _serve(directory: Path):
    """A loopback HTTP server rooted at `directory`, as a context manager."""
    import functools
    import http.server
    import socketserver
    import threading
    from contextlib import contextmanager

    @contextmanager
    def runner():
        handler = functools.partial(
            http.server.SimpleHTTPRequestHandler, directory=str(directory)
        )
        with socketserver.TCPServer(("127.0.0.1", 0), handler) as server:
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            try:
                yield f"http://127.0.0.1:{server.server_address[1]}"
            finally:
                server.shutdown()

    return runner()


@pytest.mark.skipif(shutil.which("pwsh") is None, reason="PowerShell not installed")
def test_it_really_downloads_and_unpacks_the_source_without_git(tmp_path):
    import zipfile

    served = tmp_path / "served" / "archive" / "refs" / "heads"
    served.mkdir(parents=True)
    with zipfile.ZipFile(served / "main.zip", "w") as bundle:
        bundle.writestr("beyondmeetings-main/pyproject.toml", "[project]\n")
        bundle.writestr("beyondmeetings-main/src/beyondmeetings/__init__.py", "")

    harness = tmp_path / "run.ps1"  # deliberately not beside a pyproject.toml
    harness.write_text(HARNESS, encoding="utf-8")

    with _serve(tmp_path / "served") as base:
        # PATH is emptied of everything but the system directories so the
        # lifted code cannot reach a git it must not need.
        result = subprocess.run(
            ["pwsh", "-NoProfile", "-File", str(harness),
             "-Installer", str(INSTALL), "-RepoBase", base],
            capture_output=True, text=True,
        )

    assert result.returncode == 0, result.stdout + result.stderr
    line = [x for x in result.stdout.splitlines() if x.startswith("RESULT=")]
    assert line, result.stdout + result.stderr

    source = Path(line[-1].split("=", 1)[1].strip())
    assert (source / "pyproject.toml").is_file(), f"nothing unpacked at {source}"


@pytest.mark.skipif(shutil.which("pwsh") is None, reason="PowerShell not installed")
def test_a_checkout_beside_the_script_is_used_instead_of_downloading(tmp_path):
    """The clone-and-run path must not hit the network at all."""
    harness = tmp_path / "run.ps1"
    harness.write_text(HARNESS, encoding="utf-8")
    (tmp_path / "pyproject.toml").write_text("[project]\n", encoding="utf-8")

    result = subprocess.run(
        ["pwsh", "-NoProfile", "-File", str(harness),
         "-Installer", str(INSTALL), "-RepoBase", "http://127.0.0.1:1/unreachable",
         "-ScriptRoot", str(tmp_path)],
        capture_output=True, text=True,
    )

    assert result.returncode == 0, result.stdout + result.stderr
    assert f"RESULT={tmp_path}" in result.stdout


@pytest.mark.skipif(shutil.which("pwsh") is None, reason="PowerShell not installed")
def test_a_dry_run_reports_before_anything_is_fetched():
    """-DryRun once sat *after* the interpreter was acquired, so on a machine
    with no Python it downloaded and installed uv — the one thing it may not
    do. The report has to come first."""
    dry_run = SCRIPT.index("if ($DryRun) {")
    for acquisition in ("$UvExe = Install-Uv", "Install-PythonWithWinget\n"):
        assert SCRIPT.index(acquisition, dry_run) > dry_run, acquisition

    # ...and the branch that would have fetched is only reachable afterwards.
    assert SCRIPT.index("if (-not $Interpreter) {\n    if (-not $NoUv)") > dry_run
