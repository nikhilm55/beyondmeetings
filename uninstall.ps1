# Remove beyondMeetings from Windows.
#
#   irm -useb https://raw.githubusercontent.com/nikhilm55/beyondmeetings/main/uninstall.ps1 | iex
#
# Same contract as uninstall.sh: your meetings are never touched by default.
# Recordings and transcripts live outside the program directory precisely so
# that removing the program cannot destroy them.
#
# To pass a switch:
#   & ([scriptblock]::Create((irm -useb <url>))) -PurgeData
[CmdletBinding()]
param(
    [switch]$PurgeData,
    [switch]$PurgeKeys,
    [switch]$DryRun
)

$ErrorActionPreference = "Stop"

# Same fallback as install.ps1. Without it, a session with no LOCALAPPDATA
# dies on Join-Path under "Stop" and the program becomes unremovable by its
# own uninstaller — in exactly the session where install.ps1 now succeeds.
$LocalAppData = if ($env:LOCALAPPDATA) {
    $env:LOCALAPPDATA
} else {
    Join-Path $env:USERPROFILE "AppData\Local"
}

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

$Venv = Join-Path $InstallRoot "venv"
$VenvPython = Join-Path $Venv "Scripts\python.exe"
$Command = Join-Path $Venv "Scripts\beyondmeetings.exe"
$Shim = Join-Path $BinDir "beyondmeetings.cmd"

function Say([string]$Message) { Write-Host "  $Message" }

function Remove-Thing {
    param([string]$Path, [string]$What)
    if (-not $Path -or -not (Test-Path -LiteralPath $Path)) {
        Say "already gone: $What"
        return
    }
    if ($DryRun) {
        Say "would remove: $What ($Path)"
        return
    }
    Remove-Item -LiteralPath $Path -Recurse -Force -ErrorAction SilentlyContinue
    Say "removed: $What"
}

Write-Host "beyondMeetings uninstaller"
Write-Host ""

# Resolve the real paths while Python is still installed. On Windows
# platformdirs puts the config directory at the SAME path as the data
# directory, so the config file sits inside the folder holding recordings —
# removing that folder to "clear settings" would delete a user's meetings.
$ConfigFile = $null
$DataDir = $null
$StartMenu = $null
$StartupLink = $null

if (Test-Path $VenvPython) {
    try {
        $probe = & $VenvPython -c @'
from beyondmeetings.config import DEFAULT_CONFIG_PATH, DEFAULT_DATA_DIR
from beyondmeetings.desktop_windows import shortcut_path, startup_shortcut_path
print(DEFAULT_CONFIG_PATH)
print(DEFAULT_DATA_DIR)
print(shortcut_path())
print(startup_shortcut_path())
'@ 2>$null
        $lines = @($probe) | Where-Object { $_ }
        if ($lines.Count -ge 4) {
            $ConfigFile = $lines[0]; $DataDir = $lines[1]
            $StartMenu = $lines[2]; $StartupLink = $lines[3]
        }
    } catch { }
}

# Fallbacks for a half-removed install where Python is already gone.
if (-not $ConfigFile) {
    $ConfigFile = Join-Path $LocalAppData "beyondmeetings\config.toml"
}
if (-not $DataDir) { $DataDir = Join-Path $LocalAppData "beyondmeetings" }
if (-not $StartMenu) {
    $StartMenu = Join-Path $env:APPDATA `
        "Microsoft\Windows\Start Menu\Programs\beyondMeetings.lnk"
}
if (-not $StartupLink) {
    $StartupLink = Join-Path $env:APPDATA `
        "Microsoft\Windows\Start Menu\Programs\Startup\beyondMeetings.lnk"
}

# A recording in progress would otherwise leave an orphaned capture worker
# behind, still holding the WAV open.
if ((-not $DryRun) -and (Test-Path $Command)) {
    try { & $Command stop 2>$null } catch { }
}

# Keys first, because deleting them runs through the app's own Python, which
# the removals below delete. Doing it afterwards meant every real run reported
# "already gone" and silently left the keys in Credential Manager, while
# -DryRun cheerfully claimed they had been removed.
if ($PurgeKeys) {
    if ($DryRun) {
        Say "would remove: stored API keys"
    } elseif (Test-Path $VenvPython) {
        & $VenvPython -c @'
import keyring
for name in ("groq_api_key", "anthropic_api_key", "openai_api_key", "gemini_api_key"):
    try:
        keyring.delete_password("beyondmeetings", name)
    except Exception:
        pass
'@ 2>$null
        Say "removed: stored API keys"
    } else {
        Say "cannot remove keys: the application is already gone"
    }
} else {
    Say "kept: stored API keys (-PurgeKeys to remove)"
}

Remove-Thing $StartupLink "start-at-login shortcut"
Remove-Thing $StartMenu   "Start Menu shortcut"

# Only our own shim, never the whole directory: install.ps1 honours
# BEYONDMEETINGS_BIN, so this can be a shared bin folder holding unrelated
# executables. uninstall.sh removes a single symlink for the same reason.
Remove-Thing $Shim "command shim"

# ffmpeg, only when it is in the directory we chose ourselves. With
# BEYONDMEETINGS_BIN pointing at a shared bin folder, an ffmpeg.exe there is
# far more likely to be the user's own than the one install.ps1 fetched.
if (-not $env:BEYONDMEETINGS_BIN) {
    foreach ($tool in @("ffmpeg.exe", "ffprobe.exe")) {
        $path = Join-Path $BinDir $tool
        if (Test-Path -LiteralPath $path) {
            Remove-Thing $path "bundled $tool"
        }
    }
}
if ((Test-Path -LiteralPath $BinDir) -and
    -not (Get-ChildItem -LiteralPath $BinDir -Force -ErrorAction SilentlyContinue)) {
    if ($DryRun) {
        Say "would remove: empty command directory ($BinDir)"
    } else {
        Remove-Item -LiteralPath $BinDir -Force -ErrorAction SilentlyContinue
        Say "removed: empty command directory"
    }
}

Remove-Thing $InstallRoot "program files"
Remove-Thing $ConfigFile  "settings"

if ($PurgeData) {
    Remove-Thing $DataDir "recordings and transcripts"
} elseif (Test-Path -LiteralPath $DataDir) {
    Say "kept: recordings and transcripts in $DataDir"
    Say "      use -PurgeData to delete them"
}

Write-Host ""
Say "Done. Your notes library was not touched."

# `& $Command stop` above exits non-zero when nothing is recording, which is
# the normal case, and PowerShell keeps that in $LASTEXITCODE to the end of
# the script. uninstall.cmd then announced "Uninstall failed with exit code 1"
# after an uninstall that had removed everything it was asked to. Removals here
# are all -ErrorAction SilentlyContinue, so there is no failure to report.
exit 0
