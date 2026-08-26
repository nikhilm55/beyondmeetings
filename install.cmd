@echo off
rem beyondMeetings Windows installer - the clone-and-run entry point.
rem
rem   git clone https://github.com/nikhilm55/beyondmeetings
rem   cd beyondmeetings
rem   install.cmd
rem
rem Double-clicking it in Explorer works too.
rem
rem This wrapper exists for one reason: PowerShell's default execution policy
rem on Windows client is Restricted, so ".\install.ps1" is refused outright.
rem -ExecutionPolicy Bypass applies to this single process and leaves the
rem machine's policy untouched, so nobody has to weaken their box to install.
rem
rem It also means no network fetch of the installer itself. install.ps1 sees
rem pyproject.toml next to it and installs from this checkout, which is the
rem path to take when raw.githubusercontent.com is blocked or intercepted.
setlocal

rem Prefer PowerShell 7 when it is present: it is on .NET Core, which
rem negotiates modern TLS regardless of the .NET Framework defaults that
rem trip up Windows PowerShell 5.1 on locked-down networks.
set "PS="
for /f "delims=" %%I in ('where pwsh 2^>nul') do if not defined PS set "PS=%%I"
if not defined PS set "PS=%SystemRoot%\System32\WindowsPowerShell\v1.0\powershell.exe"

if not exist "%~dp0install.ps1" (
    echo Could not find install.ps1 next to this file.
    echo Run install.cmd from inside the cloned repository.
    set "RC=1"
    goto :done
)

"%PS%" -NoProfile -ExecutionPolicy Bypass -File "%~dp0install.ps1" %*
set "RC=%ERRORLEVEL%"

:done
echo(
if not "%RC%"=="0" echo Installation failed with exit code %RC%.

rem Double-clicked from Explorer, the window closes the instant this returns
rem and the error goes unread. Started from a console, a pause is a nuisance.
rem cmdcmdline carries this file's name only in the former case.
echo %cmdcmdline% | find /i "%~nx0" >nul && pause
exit /b %RC%
