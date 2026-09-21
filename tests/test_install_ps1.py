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
import sys
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


def test_no_branch_name_is_hardcoded_as_the_default_source():
    """This repository's default branch is `dev`; a fork's may be `master`.

    A hardcoded `main` meant the piped install fetched install.ps1 from one
    revision and then installed the *source* of another — silently, and only
    on the path everybody actually uses.
    """
    building = [
        line.strip() for line in SCRIPT.splitlines()
        if "/archive/" in line and not line.lstrip().startswith("#")
    ]
    assert building, "no archive URL is built at all"
    assert any("HEAD.zip" in line for line in building), building
    assert not any('"main"' in line for line in building), building

    defaulted = [
        line.strip() for line in SCRIPT.splitlines()
        if "$Ref =" in line and not line.lstrip().startswith("#")
    ]
    assert not any('"main"' in line for line in defaulted), defaulted


def test_git_is_only_ever_a_fallback():
    """One line builds a git spec, and it sits in the else branch."""
    building = [
        line for line in SCRIPT.splitlines()
        if "git+" in line and not line.lstrip().startswith("#")
    ]
    assert len(building) == 1, building

    region = SCRIPT.split("if ($SourceDir) {", 1)[1]
    assert region.index("} else {") < region.index("git+")


def test_a_missing_source_and_missing_git_says_so_in_one_sentence():
    assert "git is not installed to clone" in SCRIPT


# --- the other things a bare machine lacks ----------------------------------


def test_python_has_three_routes_not_one():
    assert "function Install-Uv" in SCRIPT
    assert "function Install-PythonWithWinget" in SCRIPT
    assert "function Find-Python" in SCRIPT


def test_the_runtime_prerequisites_are_provisioned():
    """ffmpeg and WebView2, through the app's own code so doctor matches."""
    assert "beyondmeetings.provision_windows" in SCRIPT


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
    reasons = _line_before_each("exit 1", before)

    assert reasons, "the installer has no failure paths left to check"
    for reason in reasons:
        assert "$LogPath" in reason, f"an exit 1 with no log pointer: {reason}"


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
param(
    [string]$Installer,
    [string]$RepoBase,
    [string]$ScriptRoot = "",
    # Which of the two source URLs to drive. Both must be reachable from
    # here: the default one is what every piped install uses, and an
    # explicit ref is what a fork or a test branch uses.
    [string]$Ref = ""
)
$ErrorActionPreference = "Stop"
$ProgressPreference = "SilentlyContinue"

# The script-scope variables the lifted functions close over.
$LogPath = Join-Path ([System.IO.Path]::GetTempPath()) "bm-install-test.log"
$Repo = $RepoBase
$RefWasGiven = [bool]$Ref

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


def _unpacked_source(result, expected_name: str) -> Path:
    """The directory Get-ProjectSource returned, insisting it returned one.

    Reading RESULT= without these checks once made a test pass on a 404: the
    lifted code fell through to git and returned an empty string, and
    Path("") is the current directory — which, running from the repository,
    holds a pyproject.toml. So the returned path has to be non-empty, and it
    has to be the folder that came out of the archive this test served.
    """
    assert result.returncode == 0, result.stdout + result.stderr
    lines = [x for x in result.stdout.splitlines() if x.startswith("RESULT=")]
    assert lines, result.stdout + result.stderr

    value = lines[-1].split("=", 1)[1].strip()
    assert value, (
        "Get-ProjectSource returned nothing, so it fell back to git:\n"
        + result.stdout
    )
    source = Path(value)
    assert source.is_absolute(), source
    assert source != Path.cwd(), "that is the checkout, not a download"
    assert source.name == expected_name, (
        f"{source.name} did not come out of the archive that was served"
    )
    return source


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
    with zipfile.ZipFile(served / "topic.zip", "w") as bundle:
        bundle.writestr("beyondmeetings-topic/pyproject.toml", "[project]\n")
        bundle.writestr("beyondmeetings-topic/src/beyondmeetings/__init__.py", "")

    harness = tmp_path / "run.ps1"  # deliberately not beside a pyproject.toml
    harness.write_text(HARNESS, encoding="utf-8")

    with _serve(tmp_path / "served") as base:
        result = subprocess.run(
            ["pwsh", "-NoProfile", "-File", str(harness),
             "-Installer", str(INSTALL), "-RepoBase", base, "-Ref", "topic"],
            capture_output=True, text=True,
        )

    source = _unpacked_source(result, "beyondmeetings-topic")
    assert (source / "pyproject.toml").is_file(), f"nothing unpacked at {source}"


@pytest.mark.skipif(shutil.which("pwsh") is None, reason="PowerShell not installed")
def test_with_no_ref_it_takes_the_repository_default_branch(tmp_path):
    """The piped install asks for no ref, and GitHub resolves
    /archive/HEAD.zip to whatever the default branch is — `dev` here.

    This is the path every user is on, so it is the one worth running for
    real. It used to request a branch literally named `main`.
    """
    import zipfile

    served = tmp_path / "served" / "archive"
    served.mkdir(parents=True)
    with zipfile.ZipFile(served / "HEAD.zip", "w") as bundle:
        bundle.writestr("beyondmeetings-abc123/pyproject.toml", "[project]\n")

    harness = tmp_path / "run.ps1"
    harness.write_text(HARNESS, encoding="utf-8")

    with _serve(tmp_path / "served") as base:
        result = subprocess.run(
            ["pwsh", "-NoProfile", "-File", str(harness),
             "-Installer", str(INSTALL), "-RepoBase", base],
            capture_output=True, text=True,
        )

    source = _unpacked_source(result, "beyondmeetings-abc123")
    assert (source / "pyproject.toml").is_file()


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


# --- what the first review of this installer found --------------------------


def _line_before_each(marker: str, text: str) -> list[str]:
    """The nearest meaningful line above each `marker`, braces skipped."""
    found = []
    for block in text.split(marker)[:-1]:
        for line in reversed(block.splitlines()):
            stripped = line.strip()
            if stripped and stripped not in {"{", "}"}:
                found.append(stripped)
                break
    return found


def test_every_terminal_failure_goes_through_Fail():
    """Fail() writes to the log; Write-Host does not. Every reason an install
    stopped used to exist only on a screen the user had already closed."""
    before = SCRIPT.split(POINT_OF_NO_RETURN, 1)[0]
    reasons = _line_before_each("exit 1", before)

    assert reasons, "the installer has no failure paths left to check"
    for reason in reasons:
        assert reason.startswith("Fail "), f"a failure that skips the log: {reason}"


def test_the_commands_that_can_fail_are_logged():
    """pip's output is the reason for almost every failed install."""
    for command in ("pip", "install", "venv"):
        assert command in SCRIPT
    assert "function Invoke-Logged" in SCRIPT
    # Nothing that can fail the install may bypass it.
    assert "& $VenvPython -m pip install" not in SCRIPT


def test_the_path_is_refreshed_after_provisioning():
    """winget puts ffmpeg on the stored PATH, not on this process's, and the
    app launched below inherits ours."""
    provision = SCRIPT.index("beyondmeetings.provision_windows")
    launch = SCRIPT.index("app --setup")
    refresh = SCRIPT.index("Update-PathFromRegistry", provision)

    assert provision < refresh < launch


def test_the_path_refresh_merges_rather_than_assigns():
    body = SCRIPT.split("function Update-PathFromRegistry {", 1)[1].split("\n}", 1)[0]
    assert '$env:Path = $merged -join ";"' in body
    assert '$env:Path = ($parts -join ";")' not in body


def test_a_repo_url_ending_in_dot_git_still_yields_an_archive_url():
    assert '.EndsWith(".git")' in SCRIPT


def test_the_git_fallback_only_pins_a_ref_when_one_was_given():
    """Appending @main pins a fork whose default branch is master or dev to a
    branch it does not have."""
    assert "$RefWasGiven" in SCRIPT
    spec = SCRIPT.split("$spec = ", 1)[1].split("\n", 1)[0]
    assert '$RefWasGiven' in spec and 'git+$Repo"' in spec


def test_the_downloaded_source_is_cleaned_up():
    """Tens of megabytes of zip and unpacked tree per run, otherwise kept."""
    assert "$script:SourceScratch = $scratch" in SCRIPT
    removal = SCRIPT.index("Remove-Item -Recurse -Force $script:SourceScratch")
    assert removal > SCRIPT.index("$installed = Invoke-Logged")


def test_the_dry_run_does_not_promise_a_download_from_inside_a_checkout():
    assert "would install from this checkout, fetching nothing" in SCRIPT


def test_the_uninstaller_survives_an_empty_localappdata():
    """install.ps1 grew a fallback; the uninstaller kept the bug, which made
    the program unremovable by its own script in that same session."""
    text = UNINSTALL.read_text(encoding="utf-8")
    assert "$LocalAppData = if ($env:LOCALAPPDATA)" in text
    assert '$env:LOCALAPPDATA "' not in text


@pytest.mark.skipif(shutil.which("pwsh") is None, reason="PowerShell not installed")
def test_the_path_merge_keeps_process_only_entries(tmp_path):
    """Exercised, not grepped: the old version assigned the registry value
    over $env:Path, dropping uv's directory and anything the caller set."""
    harness = tmp_path / "path.ps1"
    harness.write_text(
        HARNESS.replace(
            '$result = Get-ProjectSource -ScriptRoot $ScriptRoot\n'
            'Write-Output "RESULT=$result"',
            '$env:Path = "/only-in-this-process;" + $env:Path\n'
            'Update-PathFromRegistry\n'
            'Write-Output "RESULT=$env:Path"',
        ),
        encoding="utf-8",
    )

    result = subprocess.run(
        ["pwsh", "-NoProfile", "-File", str(harness),
         "-Installer", str(INSTALL), "-RepoBase", "http://127.0.0.1:1/unused"],
        capture_output=True, text=True,
    )

    assert result.returncode == 0, result.stdout + result.stderr
    line = [x for x in result.stdout.splitlines() if x.startswith("RESULT=")][-1]
    assert "/only-in-this-process" in line


# Invoke-Logged runs on every install and is the thing that puts a failure's
# cause in the log, so it is executed rather than grepped. Its risk is the
# PowerShell 5.1 rule that 2>&1 on a native command makes stderr terminating
# under $ErrorActionPreference = "Stop" — a non-zero command must come back
# as a number, not an exception.
LOGGED_HARNESS = r"""
# Not $Args: that is an automatic variable, and a parameter of that name
# never binds. The harness had it, and the command ran with no arguments.
param([string]$Installer, [string]$LogFile, [string]$Exe, [string]$Code)
$ErrorActionPreference = "Stop"
$LogPath = $LogFile

$ast = [System.Management.Automation.Language.Parser]::ParseFile(
    $Installer, [ref]$null, [ref]$null)
$functions = $ast.FindAll(
    { param($node)
      $node -is [System.Management.Automation.Language.FunctionDefinitionAst] },
    $false)
Invoke-Expression (($functions | ForEach-Object { $_.Extent.Text }) -join "`n")

$exitCode = Invoke-Logged $Exe @("-c", $Code)
Write-Output "CODE=$exitCode"
"""


def _invoke_logged(tmp_path, code):
    """Run `python -c <code>` through the installer's own Invoke-Logged."""
    harness = tmp_path / "logged.ps1"
    harness.write_text(LOGGED_HARNESS, encoding="utf-8")
    log = tmp_path / "install.log"
    result = subprocess.run(
        ["pwsh", "-NoProfile", "-File", str(harness),
         "-Installer", str(INSTALL), "-LogFile", str(log),
         "-Exe", sys.executable, "-Code", code],
        capture_output=True, text=True,
    )
    text = log.read_text(encoding="utf-8") if log.exists() else ""
    return result, text


@pytest.mark.skipif(shutil.which("pwsh") is None, reason="PowerShell not installed")
def test_a_commands_output_reaches_the_log(tmp_path):
    result, log = _invoke_logged(tmp_path, "print('hello from the command')")

    assert result.returncode == 0, result.stdout + result.stderr
    assert "CODE=0" in result.stdout
    assert "hello from the command" in log
    assert "-c" in log, "the command line itself should be recorded"


@pytest.mark.skipif(shutil.which("pwsh") is None, reason="PowerShell not installed")
def test_a_failing_command_returns_its_code_instead_of_throwing(tmp_path):
    """Under 'Stop', an unguarded 2>&1 would make this an exception and the
    installer would die with a stack trace instead of its own message."""
    result, log = _invoke_logged(
        tmp_path, "import sys; sys.stderr.write('it went wrong'); sys.exit(3)"
    )

    assert result.returncode == 0, result.stdout + result.stderr
    assert "CODE=3" in result.stdout
    assert "it went wrong" in log, "stderr is where the reason lives"
