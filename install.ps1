# beyondMeetings Windows installer.
#
# Run it with one line, no download and no execution-policy change — piping to
# iex never writes a .ps1 to disk, and the policy only governs script files:
#
#   irm -useb https://raw.githubusercontent.com/nikhilm55/beyondmeetings/main/install.ps1 | iex
#
# To pass a switch, create the script block explicitly:
#
#   & ([scriptblock]::Create((irm -useb <url>))) -DryRun
#
# Mirrors install.sh: prefer a usable system Python, fall back to uv (which
# ships its own CPython), and probe by actually building a venv rather than
# trusting a version number.
[CmdletBinding()]
param(
    [switch]$DryRun,
    [switch]$NoUv
)

$ErrorActionPreference = "Stop"
$MinVersion = "3.10"

# Deliberately not the data directory: recordings and transcripts live under
# %LOCALAPPDATA%\beyondmeetings so an uninstall can remove the program without
# touching a user's meetings.
$InstallRoot = if ($env:BEYONDMEETINGS_HOME) {
    $env:BEYONDMEETINGS_HOME
} else {
    Join-Path $env:LOCALAPPDATA "beyondMeetings\app"
}
$BinDir = if ($env:BEYONDMEETINGS_BIN) {
    $env:BEYONDMEETINGS_BIN
} else {
    Join-Path $env:LOCALAPPDATA "beyondMeetings\bin"
}
$Repo = if ($env:BEYONDMEETINGS_REPO) {
    $env:BEYONDMEETINGS_REPO
} else {
    "https://github.com/nikhilm55/beyondmeetings"
}

$Venv = Join-Path $InstallRoot "venv"
$VenvPython = Join-Path $Venv "Scripts\python.exe"
$Command = Join-Path $Venv "Scripts\beyondmeetings.exe"
$Shim = Join-Path $BinDir "beyondmeetings.cmd"

function Say([string]$Message) { Write-Host "  $Message" }

function Invoke-Quiet {
    param([string]$Exe, [string[]]$Arguments)
    & $Exe @Arguments 2>$null
    return $LASTEXITCODE
}

# A version check does not prove venv works, so build one and look. This also
# disposes of the Microsoft Store stub: it resolves on PATH and then fails.
function Test-PythonUsable {
    param([string]$Exe, [string[]]$Prefix)
    try {
        $check = $Prefix + @(
            "-c",
            "import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)"
        )
        if ((Invoke-Quiet $Exe $check) -ne 0) { return $false }

        $probe = Join-Path ([System.IO.Path]::GetTempPath()) `
            ("bm-probe-" + [System.Guid]::NewGuid().ToString("N"))
        $built = Invoke-Quiet $Exe ($Prefix + @("-m", "venv", $probe))
        $ok = ($built -eq 0) -and
              (Test-Path (Join-Path $probe "Scripts\python.exe"))
        Remove-Item -Recurse -Force $probe -ErrorAction SilentlyContinue
        return $ok
    } catch {
        return $false
    }
}

function Find-Python {
    $candidates = @(
        @{ Exe = "py";      Prefix = @("-3.13") },
        @{ Exe = "py";      Prefix = @("-3.12") },
        @{ Exe = "py";      Prefix = @("-3.11") },
        @{ Exe = "py";      Prefix = @("-3.10") },
        @{ Exe = "py";      Prefix = @("-3")    },
        @{ Exe = "python";  Prefix = @()        },
        @{ Exe = "python3"; Prefix = @()        }
    )
    foreach ($candidate in $candidates) {
        $found = Get-Command $candidate.Exe -ErrorAction SilentlyContinue
        if (-not $found) { continue }
        # The Store's App Execution Alias is a stub that can open the Store
        # instead of running. Never probe it.
        if ($found.Source -and $found.Source -like "*\WindowsApps\*") { continue }
        if (Test-PythonUsable $candidate.Exe $candidate.Prefix) {
            return $candidate
        }
    }
    return $null
}

Write-Host "beyondMeetings installer"
Write-Host ""

$Interpreter = Find-Python
$UsingUv = $false

if (-not $Interpreter) {
    Say "No usable Python $MinVersion+ with venv support found."
    if ($NoUv) {
        Write-Error @"
Install Python $MinVersion or newer from https://www.python.org/downloads/
(tick "Add python.exe to PATH"), then run this installer again.
"@
        exit 1
    }
    Say "Falling back to uv, which installs its own Python."
    $UsingUv = $true
} else {
    # 2>$null, not 2>&1: under $ErrorActionPreference = "Stop", PowerShell 5.1
    # turns a native command's stderr into terminating errors. Python 3 prints
    # its version to stdout, so nothing is lost.
    $shown = (& $Interpreter.Exe @($Interpreter.Prefix + @("--version")) 2>$null)
    Say "Using system Python: $shown"
}

if ($DryRun) {
    if ($UsingUv) {
        Write-Host "Dry run: would bootstrap uv and use its bundled Python."
    } else {
        Write-Host ("Dry run: would use " +
            ($Interpreter.Exe + " " + ($Interpreter.Prefix -join " ")).Trim() +
            " and install to $InstallRoot.")
    }
    exit 0
}

New-Item -ItemType Directory -Force -Path $InstallRoot, $BinDir | Out-Null

if ($UsingUv) {
    if (-not (Get-Command uv -ErrorAction SilentlyContinue)) {
        Say "Downloading uv from astral.sh..."
        Invoke-RestMethod -UseBasicParsing https://astral.sh/uv/install.ps1 | Invoke-Expression
        $env:Path = (Join-Path $env:USERPROFILE ".local\bin") + ";" + $env:Path
    }
    & uv python install $MinVersion
    # --seed puts pip in the venv; without it the install below dies on
    # "No module named pip".
    & uv venv --seed --python $MinVersion $Venv
} else {
    & $Interpreter.Exe @($Interpreter.Prefix + @("-m", "venv", $Venv))
}

if (-not (Test-Path $VenvPython)) {
    Write-Error "The environment at $Venv was not created. Nothing was installed."
    exit 1
}

Say "Installing beyondMeetings..."
& $VenvPython -m pip install --quiet --upgrade pip

# $PSScriptRoot is empty when this script is piped into iex, which is the
# documented path — that falls through to the git install.
$localProject = if ($PSScriptRoot) { Join-Path $PSScriptRoot "pyproject.toml" } else { $null }
if ($localProject -and (Test-Path $localProject)) {
    & $VenvPython -m pip install --quiet "$PSScriptRoot[desktop]"
} else {
    & $VenvPython -m pip install --quiet "beyondmeetings[desktop] @ git+$Repo"
}
if ($LASTEXITCODE -ne 0) {
    Write-Error "Installing the application failed. Nothing else was changed."
    exit 1
}

# A shim rather than a PATH edit: this script never rewrites the user's PATH
# registry value. If the directory is not on PATH we say so and move on.
@"
@echo off
"$Command" %*
"@ | Set-Content -Path $Shim -Encoding Oem
Say "Installed the beyondmeetings command to $BinDir"

$onPath = ($env:Path -split ";" | Where-Object { $_ -and $_.TrimEnd("\") -ieq $BinDir.TrimEnd("\") })
if (-not $onPath) {
    Say "Note: $BinDir is not on your PATH — add it to use 'beyondmeetings' in a terminal."
}

# Shell integration is convenience, never a prerequisite for recording, so a
# failure here warns and carries on. doctor can repair it later.
try {
    & $VenvPython -c "from beyondmeetings.desktop_windows import install_shortcut; install_shortcut()"
    if ($LASTEXITCODE -eq 0) { Say "Added beyondMeetings to the Start Menu" }
    else { Say "Could not add the Start Menu shortcut — run 'beyondmeetings doctor' to retry." }
} catch {
    Say "Could not add the Start Menu shortcut — run 'beyondmeetings doctor' to retry."
}

# Only refresh an existing login entry; installing must not silently opt a user
# into start-at-login. Same rule as refresh_installed_autostart on Linux.
& $VenvPython -c @'
from beyondmeetings.desktop_windows import install_startup_shortcut, startup_shortcut_path
if startup_shortcut_path().is_file():
    install_startup_shortcut()
'@ 2>$null

Write-Host ""
& $VenvPython -c "import sys; from beyondmeetings.desktop import server_is_running; sys.exit(0 if server_is_running() else 1)" 2>$null
if ($LASTEXITCODE -eq 0) {
    Say "beyondMeetings is already running — open http://127.0.0.1:7788/setup"
    exit 0
}

Say "Opening the desktop app..."
& $Command app --setup
