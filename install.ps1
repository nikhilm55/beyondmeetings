# beyondMeetings Windows installer. Run from PowerShell 5+.
[CmdletBinding()]
param([switch]$DryRun)

$ErrorActionPreference = "Stop"
$InstallRoot = if ($env:BEYONDMEETINGS_HOME) {
    $env:BEYONDMEETINGS_HOME
} else {
    Join-Path $env:LOCALAPPDATA "beyondMeetings\app"
}
$Repo = if ($env:BEYONDMEETINGS_REPO) {
    $env:BEYONDMEETINGS_REPO
} else {
    "https://github.com/nikhilm55/beyondmeetings"
}

$Python = Get-Command py -ErrorAction SilentlyContinue
if (-not $Python) { $Python = Get-Command python -ErrorAction SilentlyContinue }
if (-not $Python) {
    throw "Python 3.10 or newer is required. Install it from python.org, then retry."
}

if ($DryRun) {
    Write-Host "Would install beyondMeetings to $InstallRoot"
    exit 0
}

New-Item -ItemType Directory -Force -Path $InstallRoot | Out-Null
$Venv = Join-Path $InstallRoot "venv"
if ($Python.Name -eq "py.exe") { & $Python.Source -3 -m venv $Venv }
else { & $Python.Source -m venv $Venv }

$VenvPython = Join-Path $Venv "Scripts\python.exe"
& $VenvPython -m pip install --quiet --upgrade pip

$LocalProject = Join-Path $PSScriptRoot "pyproject.toml"
if ($PSScriptRoot -and (Test-Path $LocalProject)) {
    & $VenvPython -m pip install --quiet "$PSScriptRoot[desktop]"
} else {
    & $VenvPython -m pip install --quiet "beyondmeetings[desktop] @ git+$Repo"
}

$Command = Join-Path $Venv "Scripts\beyondmeetings.exe"
$Programs = Join-Path $env:APPDATA "Microsoft\Windows\Start Menu\Programs"
$Shortcut = Join-Path $Programs "beyondMeetings.lnk"
$Shell = New-Object -ComObject WScript.Shell
$Link = $Shell.CreateShortcut($Shortcut)
$Link.TargetPath = $Command
$Link.Arguments = "app"
$Link.WorkingDirectory = $InstallRoot
$Link.Description = "Private meeting recorder and local notes app"
$Link.Save()

Write-Host "beyondMeetings installed. Opening setup..."
& $Command app --setup
