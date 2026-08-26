@echo off
rem beyondMeetings Windows uninstaller - the clone-and-run entry point.
rem
rem   uninstall.cmd            remove the program, keep recordings
rem   uninstall.cmd -DryRun    report what would be removed, change nothing
rem
rem Same wrapper as install.cmd, and for the same reason: PowerShell's default
rem execution policy on Windows client refuses ".\uninstall.ps1", and -Bypass
rem here applies to this process alone.
setlocal

set "PS="
for /f "delims=" %%I in ('where pwsh 2^>nul') do if not defined PS set "PS=%%I"
if not defined PS set "PS=%SystemRoot%\System32\WindowsPowerShell\v1.0\powershell.exe"

if not exist "%~dp0uninstall.ps1" (
    echo Could not find uninstall.ps1 next to this file.
    echo Run uninstall.cmd from inside the cloned repository.
    set "RC=1"
    goto :done
)

"%PS%" -NoProfile -ExecutionPolicy Bypass -File "%~dp0uninstall.ps1" %*
set "RC=%ERRORLEVEL%"

:done
echo(
if not "%RC%"=="0" echo Uninstall failed with exit code %RC%.

echo %cmdcmdline% | find /i "%~nx0" >nul && pause
exit /b %RC%
