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

$Venv = Join-Path $InstallRoot "venv"
$VenvPython = Join-Path $Venv "Scripts\python.exe"
$Command = Join-Path $Venv "Scripts\beyondmeetings.exe"

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
    $ConfigFile = Join-Path $env:LOCALAPPDATA "beyondmeetings\config.toml"
}
if (-not $DataDir) { $DataDir = Join-Path $env:LOCALAPPDATA "beyondmeetings" }
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
    try { & $Command stop 2>&1 | Out-Null } catch { }
}

Remove-Thing $StartupLink "start-at-login shortcut"
Remove-Thing $StartMenu   "Start Menu shortcut"
Remove-Thing $BinDir      "command shim"
Remove-Thing $InstallRoot "program files"
Remove-Thing $ConfigFile  "settings"

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
'@ 2>&1 | Out-Null
        Say "removed: stored API keys"
    } else {
        Say "cannot remove keys: the application is already gone"
    }
} else {
    Say "kept: stored API keys (-PurgeKeys to remove)"
}

if ($PurgeData) {
    Remove-Thing $DataDir "recordings and transcripts"
} elseif (Test-Path -LiteralPath $DataDir) {
    Say "kept: recordings and transcripts in $DataDir"
    Say "      use -PurgeData to delete them"
}

Write-Host ""
Say "Done. Your notes library was not touched."
