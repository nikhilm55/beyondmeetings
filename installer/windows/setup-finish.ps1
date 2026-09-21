# Turns the copied payload into a working installation. Run by the setup.exe
# once its files are on disk, and never by a user directly.
#
# Everything it needs is already in $Root: a relocatable CPython under
# runtime\, and every wheel under wheels\. It therefore makes no network
# request at all, which is the whole point of shipping a setup.exe — the
# machine this runs on may have no working proxy, no certificate store worth
# trusting, and no way to reach pypi.org.
#
# It builds a venv rather than importing the wheels into the runtime
# directly, because a venv is the layout the rest of the application already
# assumes: `doctor`, the Start Menu shortcut and uninstall.ps1 all look for
# venv\Scripts\beyondmeetings.exe. Building it *here* rather than at build
# time is also what makes the payload relocatable — pip writes the absolute
# path of the interpreter into every console script it generates, so a venv
# created on a build agent would point at a directory that does not exist on
# the user's machine.
[CmdletBinding()]
param(
    # ...\beyondMeetings\app — holds runtime\, wheels\ and the venv.
    [Parameter(Mandatory = $true)][string]$Root,
    # ...\beyondMeetings\bin — holds ffmpeg and the command shim.
    [Parameter(Mandatory = $true)][string]$BinDir
)

$ErrorActionPreference = "Stop"
# A non-zero exit from pip is handled below by reading $LASTEXITCODE. Without
# this, PowerShell 7 raises on it first and the log loses pip's own message,
# which is the only thing that ever explains a failed install.
$PSNativeCommandUseErrorActionPreference = $false
$ProgressPreference = "SilentlyContinue"

$LogPath = Join-Path ([System.IO.Path]::GetTempPath()) "beyondmeetings-setup.log"

function Write-Log([string]$Line) {
    try {
        Add-Content -Path $LogPath -Value $Line -Encoding UTF8 -ErrorAction Stop
    } catch { }
}

function Invoke-Logged {
    param([string]$Exe, [string[]]$Arguments)
    Write-Log "  > $Exe $($Arguments -join ' ')"
    $previous = $ErrorActionPreference
    # 2>&1 turns a native command's stderr into error records, and under
    # "Stop" PowerShell 5.1 makes the first one terminating — so a pip
    # deprecation warning would abort a perfectly good install.
    $ErrorActionPreference = "Continue"
    try {
        & $Exe @Arguments 2>&1 | ForEach-Object { Write-Log ([string]$_) }
        return $LASTEXITCODE
    } finally {
        $ErrorActionPreference = $previous
    }
}

try { Remove-Item -Force $LogPath -ErrorAction SilentlyContinue } catch { }
Write-Log "beyondMeetings setup finishing at $(Get-Date -Format o)"
Write-Log "  Root:   $Root"
Write-Log "  BinDir: $BinDir"
Write-Log "  Host:   $($PSVersionTable.PSVersion) on $([System.Environment]::OSVersion.VersionString)"

$Runtime = Join-Path $Root "runtime\python.exe"
$Wheels = Join-Path $Root "wheels"
$Venv = Join-Path $Root "venv"
$VenvPython = Join-Path $Venv "Scripts\python.exe"
$Command = Join-Path $Venv "Scripts\beyondmeetings.exe"

if (-not (Test-Path $Runtime)) {
    Write-Log "FATAL: no interpreter at $Runtime"
    exit 2
}
if (-not (Test-Path $Wheels)) {
    Write-Log "FATAL: no wheels at $Wheels"
    exit 3
}

# An upgrade over a previous install: the old venv holds the old version's
# files and pip would merge the two. Rebuilding from the bundled wheels is
# both faster and the only way to be sure what is installed.
if (Test-Path $Venv) {
    Write-Log "  Removing the previous environment."
    Remove-Item -Recurse -Force $Venv -ErrorAction SilentlyContinue
}

Write-Log "  Creating the environment."
if ((Invoke-Logged $Runtime @("-m", "venv", $Venv)) -ne 0 -or
    -not (Test-Path $VenvPython)) {
    Write-Log "FATAL: the environment at $Venv was not created."
    exit 4
}

# --no-index is the load-bearing flag: without it a machine with a reachable
# pypi.org would silently resolve against it, and a machine without one would
# hang on a connection timeout instead of failing fast.
Write-Log "  Installing beyondMeetings from the bundled wheels."
$installed = Invoke-Logged $VenvPython @(
    "-m", "pip", "install",
    "--no-index", "--find-links", $Wheels,
    "--no-warn-script-location", "--disable-pip-version-check",
    "beyondmeetings[tray]")

if ($installed -ne 0 -or -not (Test-Path $Command)) {
    Write-Log "FATAL: pip exited $installed and there is no $Command."
    exit 5
}

# Past this line the application is installed and working. Nothing below may
# change the exit code: every remaining step is a convenience that
# `beyondmeetings doctor` can repair later, and reporting a good install as a
# failure is worse than the missing extra. install.ps1 draws the same line in
# the same place and for the same reason.

# ~100 MB of wheels that will never be read again. The uninstaller does not
# mind them being gone; Inno Setup skips files it recorded and cannot find.
try {
    Remove-Item -Recurse -Force $Wheels -ErrorAction SilentlyContinue
    Write-Log "  Reclaimed the bundled wheels."
} catch { }

# A shim rather than a PATH edit, matching install.ps1: this installer never
# rewrites the user's PATH. ffmpeg needs no entry either — it sits in $BinDir,
# which the application searches alongside PATH.
try {
    New-Item -ItemType Directory -Force -Path $BinDir | Out-Null
    @"
@echo off
"$Command" %*
"@ | Set-Content -Path (Join-Path $BinDir "beyondmeetings.cmd") -Encoding Oem
    Write-Log "  Wrote the command shim to $BinDir"
} catch {
    Write-Log "  ! Could not write the command shim: $($_.Exception.Message)"
}

# The Start Menu shortcut targets pythonw.exe so no console flashes. venv
# copies it from the runtime, which always has one — but if that ever stops
# being true the icon would point at nothing, and this is the only place the
# reason would be recorded.
$Windowless = Join-Path $Venv "Scripts\pythonw.exe"
if (-not (Test-Path $Windowless)) {
    Write-Log "  ! No pythonw.exe in the environment — the app icon will not work."
}

$ffmpeg = Join-Path $BinDir "ffmpeg.exe"
if (Test-Path $ffmpeg) {
    Write-Log "  ffmpeg: $ffmpeg"
} else {
    Write-Log "  ! No ffmpeg at $ffmpeg — 'beyondmeetings doctor' can fetch one."
}

Write-Log "beyondMeetings is installed."
exit 0
