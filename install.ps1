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
# It assumes a machine with *nothing* on it. A freshly imaged Windows has no
# Python, no git, no ffmpeg, and — on Windows 10 — often no WebView2 runtime,
# so each of those is detected and fetched rather than assumed. Every step has
# a second route, and once the application itself is installed nothing that
# follows can turn the run into a failure: a prerequisite we could not fetch is
# reported, and `beyondmeetings doctor` can retry it later.
[CmdletBinding()]
param(
    [switch]$DryRun,
    [switch]$NoUv,
    # Install without opening the app. What CI uses, and what you want when
    # setting a machine up for someone else.
    [switch]$NoLaunch
)

$ErrorActionPreference = "Stop"

# PowerShell 7 can turn a non-zero exit from a native command into a
# terminating error. This script checks $LASTEXITCODE deliberately — pip
# failing has a message worth printing, and uv failing on one Python version
# is meant to fall through and try another — so that behaviour is switched
# off rather than left to the session's settings. The variable does not exist
# on Windows PowerShell 5.1, where assigning it is harmless.
$PSNativeCommandUseErrorActionPreference = $false

# Invoke-WebRequest on Windows PowerShell 5.1 renders a progress bar per chunk,
# which turns a 100 MB download into a several-minute one. Silencing it is the
# single biggest speed difference in this script.
$ProgressPreference = "SilentlyContinue"

# Windows PowerShell 5.1 is on .NET Framework, whose SecurityProtocol default
# can still be TLS 1.0 on a locked-down or unpatched machine. The downloads
# below then die with "The underlying connection was closed". -bor rather
# than assignment so PowerShell 7's TLS 1.3 is not knocked out; try/catch
# because the enum member is absent on very old .NET.
try {
    [Net.ServicePointManager]::SecurityProtocol =
        [Net.ServicePointManager]::SecurityProtocol -bor [Net.SecurityProtocolType]::Tls12
} catch { }

# Corporate machines reach the internet through an authenticating proxy that
# Windows already holds credentials for. Without this, every fetch here gets a
# 407 that looks like the network being down.
try {
    [Net.WebRequest]::DefaultWebProxy.Credentials =
        [Net.CredentialCache]::DefaultNetworkCredentials
} catch { }

$MinVersion = "3.10"
# What we install when we have to install one. Deliberately not $MinVersion:
# 3.10 is the floor we still *support*, but a fresh machine should get a
# version every dependency publishes wheels for, so nothing needs a compiler.
$PreferredVersion = "3.12"

# LOCALAPPDATA is set on every sane Windows, but not inside every service or
# stripped-down session, and an empty base path would install into C:\.
$LocalAppData = if ($env:LOCALAPPDATA) {
    $env:LOCALAPPDATA
} else {
    Join-Path $env:USERPROFILE "AppData\Local"
}

# Deliberately not the data directory: recordings and transcripts live under
# %LOCALAPPDATA%\beyondmeetings so an uninstall can remove the program without
# touching a user's meetings.
$InstallRoot = if ($env:BEYONDMEETINGS_HOME) {
    $env:BEYONDMEETINGS_HOME
} else {
    Join-Path $LocalAppData "beyondMeetings\app"
}
$BinDir = if ($env:BEYONDMEETINGS_BIN) {
    $env:BEYONDMEETINGS_BIN
} else {
    Join-Path $LocalAppData "beyondMeetings\bin"
}
$Repo = if ($env:BEYONDMEETINGS_REPO) {
    $env:BEYONDMEETINGS_REPO
} else {
    "https://github.com/nikhilm55/beyondmeetings"
}
$Ref = if ($env:BEYONDMEETINGS_REF) { $env:BEYONDMEETINGS_REF } else { "main" }

$Venv = Join-Path $InstallRoot "venv"
$VenvPython = Join-Path $Venv "Scripts\python.exe"
$Command = Join-Path $Venv "Scripts\beyondmeetings.exe"
$Shim = Join-Path $BinDir "beyondmeetings.cmd"

# A fresh machine is exactly where a failure is hardest to report, so keep a
# transcript of the run somewhere the user can find and paste.
$LogPath = Join-Path ([System.IO.Path]::GetTempPath()) "beyondmeetings-install.log"
try { Remove-Item -Force $LogPath -ErrorAction SilentlyContinue } catch { }

function Write-Log([string]$Line) {
    try {
        Add-Content -Path $LogPath -Value $Line -Encoding UTF8 -ErrorAction Stop
    } catch { }
}

function Say([string]$Message) {
    Write-Host "  $Message"
    Write-Log "  $Message"
}

function Warn([string]$Message) {
    Write-Host "  ! $Message" -ForegroundColor Yellow
    Write-Log "  ! $Message"
}

Write-Log "beyondMeetings install started $(Get-Date -Format o)"
Write-Log "PowerShell $($PSVersionTable.PSVersion) on $([Environment]::OSVersion.VersionString)"

# Out-Null as well as 2>$null: without it a chatty command (winget prints
# dozens of lines) returns its whole stdout to the caller alongside the exit
# code, and `$code -ne 0` then compares against an array.
function Invoke-Quiet {
    param([string]$Exe, [string[]]$Arguments)
    & $Exe @Arguments 2>$null | Out-Null
    return $LASTEXITCODE
}

function Get-File {
    param([string]$Url, [string]$Destination)
    Write-Log "  fetching $Url"
    Invoke-WebRequest -UseBasicParsing -Uri $Url -OutFile $Destination
}

function Expand-Zip {
    param([string]$Archive, [string]$Destination)
    # .NET directly rather than Expand-Archive: it is markedly faster on 5.1,
    # and Expand-Archive is the fallback for the rare box where the assembly
    # will not load.
    try {
        Add-Type -AssemblyName System.IO.Compression.FileSystem
        [System.IO.Compression.ZipFile]::ExtractToDirectory($Archive, $Destination)
    } catch {
        Expand-Archive -Path $Archive -DestinationPath $Destination -Force
    }
}

# winget and anything else installed mid-run lands on the PATH held in the
# registry, not in the environment this process inherited at launch.
function Update-PathFromRegistry {
    $parts = @(
        [Environment]::GetEnvironmentVariable("Path", "Machine"),
        [Environment]::GetEnvironmentVariable("Path", "User")
    ) | Where-Object { $_ }
    if ($parts) { $env:Path = ($parts -join ";") }
}

function Test-Winget {
    return [bool](Get-Command winget -ErrorAction SilentlyContinue)
}

# --- finding, or acquiring, a Python -----------------------------------------

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

# Returns the path to uv, or $null. uv is preferred over winget for this
# because it needs no package manager, no admin and no reboot.
function Install-Uv {
    $existing = Get-Command uv -ErrorAction SilentlyContinue
    if ($existing) { return $existing.Source }

    Say "Downloading uv from astral.sh..."
    try {
        # Out-Null so the bootstrap's own pipeline output cannot end up in this
        # function's return value, which is meant to be a path or $null.
        Invoke-RestMethod -UseBasicParsing https://astral.sh/uv/install.ps1 |
            Invoke-Expression | Out-Null
    } catch {
        Warn "Could not fetch uv: $($_.Exception.Message)"
        return $null
    }

    # uv's installer adds itself to the *stored* PATH, so look where it puts
    # itself rather than trusting this process's environment.
    $env:Path = (Join-Path $env:USERPROFILE ".local\bin") + ";" + $env:Path
    Update-PathFromRegistry
    $env:Path = (Join-Path $env:USERPROFILE ".local\bin") + ";" + $env:Path

    $found = Get-Command uv -ErrorAction SilentlyContinue
    if ($found) { return $found.Source }

    $literal = Join-Path $env:USERPROFILE ".local\bin\uv.exe"
    if (Test-Path $literal) { return $literal }
    return $null
}

# Last resort: winget. Present on current Windows 11, missing from plenty of
# Windows 10 machines, which is exactly why it is not the first choice.
function Install-PythonWithWinget {
    if (-not (Test-Winget)) {
        Write-Log "  winget is not available"
        return $null
    }
    Say "Installing Python $PreferredVersion with winget..."
    $code = Invoke-Quiet "winget" @(
        "install", "--id", "Python.Python.$PreferredVersion", "--exact",
        "--source", "winget", "--silent", "--scope", "user",
        "--accept-package-agreements", "--accept-source-agreements",
        "--disable-interactivity"
    )
    Write-Log "  winget exited $code"
    Update-PathFromRegistry
    return Find-Python
}

# --- where the project itself comes from --------------------------------------

# Returns a directory containing pyproject.toml, or $null meaning "install
# from git+". The zip route exists because a freshly installed Windows has no
# git, and `pip install ... @ git+<url>` fails outright without one — which is
# the single most likely reason this installer ever failed on a clean machine.
function Get-ProjectSource {
    # $ScriptRoot is a parameter rather than a direct read of $PSScriptRoot so
    # the test suite can drive both branches. It is empty when this script is
    # piped into iex, which is the documented install path and the one that
    # falls through to the download below.
    param([string]$ScriptRoot = $PSScriptRoot)

    if ($ScriptRoot -and (Test-Path (Join-Path $ScriptRoot "pyproject.toml"))) {
        Say "Installing from this checkout."
        return $ScriptRoot
    }

    $zipUrl = "$($Repo.TrimEnd('/'))/archive/refs/heads/$Ref.zip"
    $scratch = Join-Path ([System.IO.Path]::GetTempPath()) `
        ("bm-src-" + [System.Guid]::NewGuid().ToString("N"))
    $unpacked = Join-Path $scratch "src"
    New-Item -ItemType Directory -Force -Path $scratch | Out-Null
    $archive = Join-Path $scratch "source.zip"

    try {
        Say "Downloading the project source..."
        Get-File -Url $zipUrl -Destination $archive
        Expand-Zip -Archive $archive -Destination $unpacked
    } catch {
        Warn "Could not download the source: $($_.Exception.Message)"
        if (Get-Command git -ErrorAction SilentlyContinue) {
            Say "Falling back to git."
            return $null
        }
        throw ("Could not download $zipUrl, and git is not installed to clone " +
               "it instead. Check the network, or install git and re-run.")
    }

    $extracted = Get-ChildItem -Path $unpacked -Directory |
        Where-Object { Test-Path (Join-Path $_.FullName "pyproject.toml") } |
        Select-Object -First 1
    if (-not $extracted) {
        throw "The downloaded archive did not contain a pyproject.toml."
    }
    return $extracted.FullName
}

# --- the run ------------------------------------------------------------------

Write-Host "beyondMeetings installer"
Write-Host ""

$Interpreter = Find-Python
$UsingUv = $false
$UvExe = $null
$HaveGit = [bool](Get-Command git -ErrorAction SilentlyContinue)

if ($Interpreter) {
    # 2>$null, not 2>&1: under $ErrorActionPreference = "Stop", PowerShell 5.1
    # turns a native command's stderr into terminating errors. Python 3 prints
    # its version to stdout, so nothing is lost.
    $shown = (& $Interpreter.Exe @($Interpreter.Prefix + @("--version")) 2>$null)
    Say "Using system Python: $shown"
} else {
    Say "No usable Python $MinVersion+ with venv support found."
}

# The dry run reports and stops, before anything is fetched. It used to sit
# after the interpreter was acquired, which meant `-DryRun` on a machine with
# no Python downloaded and installed uv — the one thing a dry run may not do.
if ($DryRun) {
    if ($Interpreter) {
        Write-Host ("Dry run: would use " +
            ($Interpreter.Exe + " " + ($Interpreter.Prefix -join " ")).Trim() +
            " and install to $InstallRoot.")
    } elseif (-not $NoUv) {
        Write-Host "Dry run: would bootstrap uv and use its bundled Python."
    } elseif (Test-Winget) {
        Write-Host "Dry run: would install Python $PreferredVersion with winget."
    } else {
        Write-Host "Dry run: no Python, no uv (-NoUv) and no winget — would stop here." `
            -ForegroundColor Red
        Write-Host "Details: $LogPath"
        exit 1
    }
    if (-not $HaveGit) {
        Write-Host "Dry run: git is absent, so the source would be downloaded as a zip."
    }
    exit 0
}

if (-not $Interpreter) {
    if (-not $NoUv) {
        $UvExe = Install-Uv
        if ($UvExe) {
            $UsingUv = $true
            Say "Using uv at $UvExe, which brings its own Python."
        }
    }

    if (-not $UsingUv) {
        # Either -NoUv, or uv could not be reached. winget is the other way to
        # get a Python onto a bare machine without asking the user to.
        $Interpreter = Install-PythonWithWinget
        if ($Interpreter) {
            Say "winget installed Python; using it."
        }
    }

    if (-not $UsingUv -and -not $Interpreter) {
        Write-Host ""
        Write-Host "Could not find or install a Python $MinVersion+." -ForegroundColor Red
        Write-Host "Install one from https://www.python.org/downloads/ (tick"
        Write-Host "`"Add python.exe to PATH`"), then run this installer again."
        Write-Host "Details: $LogPath"
        exit 1
    }
}

New-Item -ItemType Directory -Force -Path $InstallRoot, $BinDir | Out-Null

if ($UsingUv) {
    & $UvExe python install $PreferredVersion
    if ($LASTEXITCODE -ne 0) {
        Warn "uv could not install Python $PreferredVersion; trying $MinVersion."
        & $UvExe python install $MinVersion
    }
    # --seed puts pip in the venv; without it the install below dies on
    # "No module named pip".
    & $UvExe venv --seed --python $PreferredVersion $Venv
    if ($LASTEXITCODE -ne 0) {
        & $UvExe venv --seed --python $MinVersion $Venv
    }
} else {
    & $Interpreter.Exe @($Interpreter.Prefix + @("-m", "venv", $Venv))
}

if (-not (Test-Path $VenvPython)) {
    Write-Host ""
    Write-Host "The environment at $Venv was not created. Nothing was installed." -ForegroundColor Red
    Write-Host "Details: $LogPath"
    exit 1
}

Say "Installing beyondMeetings..."
& $VenvPython -m pip install --quiet --disable-pip-version-check --upgrade pip

try {
    $SourceDir = Get-ProjectSource
} catch {
    Write-Host ""
    Write-Host $_.Exception.Message -ForegroundColor Red
    Write-Host "Nothing was installed. Details: $LogPath"
    exit 1
}
if ($SourceDir) {
    & $VenvPython -m pip install --quiet --disable-pip-version-check "$SourceDir[desktop]"
} else {
    & $VenvPython -m pip install --quiet --disable-pip-version-check `
        "beyondmeetings[desktop] @ git+$Repo@$Ref"
}
if ($LASTEXITCODE -ne 0) {
    Write-Host ""
    Write-Host "Installing the application failed. Nothing else was changed." -ForegroundColor Red
    Write-Host "Details: $LogPath"
    exit 1
}

# Past this line the application is installed and working. Nothing below may
# exit non-zero: every remaining step is an integration or a convenience that
# `beyondmeetings doctor` can repair later, and reporting a good install as a
# failure is worse than the missing extra.

# A shim rather than a PATH edit: this script never rewrites the user's PATH
# registry value. If the directory is not on PATH we say so and move on.
@"
@echo off
"$Command" %*
"@ | Set-Content -Path $Shim -Encoding Oem
Say "Installed the beyondmeetings command to $BinDir"

# ffmpeg and the WebView2 runtime, fetched by the application's own code so
# that `doctor` repairs them exactly the same way. It prints a row each and
# never fails: ffmpeg lands in $BinDir, which the app searches alongside PATH,
# so no PATH edit is needed for it either.
Say "Checking the other things a bare Windows is missing..."
try {
    & $VenvPython -m beyondmeetings.provision_windows
} catch {
    Warn "Could not check prerequisites: $($_.Exception.Message)"
    Warn "Run 'beyondmeetings doctor' to see what is missing."
}

# Shell integration is convenience, never a prerequisite for recording, so a
# failure here warns and carries on. doctor can repair it later.
try {
    & $VenvPython -c "from beyondmeetings.desktop_windows import install_shortcut; install_shortcut()"
    if ($LASTEXITCODE -eq 0) { Say "Added beyondMeetings to the Start Menu" }
    else { Warn "Could not add the Start Menu shortcut — run 'beyondmeetings doctor' to retry." }
} catch {
    Warn "Could not add the Start Menu shortcut — run 'beyondmeetings doctor' to retry."
}

# Only refresh an existing login entry; installing must not silently opt a user
# into start-at-login. Same rule as refresh_installed_autostart on Linux.
try {
    & $VenvPython -c @'
from beyondmeetings.desktop_windows import install_startup_shortcut, startup_shortcut_path
if startup_shortcut_path().is_file():
    install_startup_shortcut()
'@ 2>$null
} catch { }

$onPath = ($env:Path -split ";" | Where-Object { $_ -and $_.TrimEnd("\") -ieq $BinDir.TrimEnd("\") })
if (-not $onPath) {
    Say "Note: $BinDir is not on your PATH — add it to use 'beyondmeetings' in a terminal."
}

Write-Host ""
Write-Host "beyondMeetings is installed." -ForegroundColor Green
Say "Log: $LogPath"

try {
    & $VenvPython -c "import sys; from beyondmeetings.desktop import server_is_running; sys.exit(0 if server_is_running() else 1)" 2>$null
    $running = ($LASTEXITCODE -eq 0)
} catch {
    $running = $false
}
if ($running) {
    Say "It is already running — open http://127.0.0.1:7788/setup"
    exit 0
}

if ($NoLaunch) {
    Say "Not opening the app (-NoLaunch). Start it from the Start Menu."
    exit 0
}

Say "Opening the desktop app..."
$appCode = 0
try {
    & $Command app --setup
    $appCode = $LASTEXITCODE
} catch {
    Warn "The app did not open: $($_.Exception.Message)"
    $appCode = 1
}
if ($appCode -ne 0) {
    Warn "The app window did not open. The same page works in a browser:"
    Warn "run 'beyondmeetings serve' and open http://127.0.0.1:7788/setup"
}

# The install succeeded whatever the app did with its own window, and the
# caller (install.cmd) reports a non-zero exit as a failed installation.
exit 0
