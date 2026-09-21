# The offline Windows installer

`beyondMeetings-Setup-x64.exe` is one file a person double-clicks. It needs no
Python, no git, no curl, no package manager, no administrator password and no
working internet connection.

That last one is the design constraint everything else follows from. The
one-line installer (`install.ps1`) fetches its prerequisites at install time,
which is the right trade for a developer machine and the wrong one for
somebody on a locked-down laptop whose proxy eats `raw.githubusercontent.com`.
So this build resolves the whole dependency tree on a build agent and ships
it inside the installer.

## What is in it

| Piece | Where it comes from | Why that one |
|---|---|---|
| CPython 3.12, 64-bit | [python-build-standalone](https://github.com/astral-sh/python-build-standalone), `install_only` | Relocatable — it can be copied into `%LOCALAPPDATA%` and run from there. The same builds `uv` hands out. 3.12 rather than the newest, so every dependency has a wheel and nothing needs a compiler |
| Every wheel | `pip wheel` run **with that interpreter** | A wheel built by the build agent's own Python can be the wrong ABI |
| `ffmpeg.exe`, `ffprobe.exe` | The same URL and the same extraction code the application uses at runtime | One source of truth, so the installer and `doctor` cannot drift |

Deliberately *not* included: `pywebview` and the WebView2 runtime. The app is
used in a browser, so a native window would only add a Microsoft runtime to
fetch on a machine that may not be able to fetch anything. `install.ps1` still
ships both, and `doctor` still offers WebView2 to anyone who wants the window.

## The files here

| File | Role |
|---|---|
| `build_payload.py` | Downloads and lays out the three pieces above. Every network edge is injected, so it is unit-tested on Linux |
| `beyondmeetings.iss` | The Inno Setup script: where things go, the Start Menu entry, the uninstaller |
| `setup-finish.ps1` | Runs once, on the user's machine, after the files are copied. Builds the venv and installs the bundled wheels with `--no-index` |

## Why the venv is built on the user's machine

pip writes the absolute path of the interpreter into every console script it
generates. A virtual environment built on a build agent would point
`beyondmeetings.exe` at a directory that does not exist on the user's disk.
Building it in `setup-finish.ps1` is what makes the payload relocatable — and
it produces exactly the layout `install.ps1` produces, so `doctor`,
`uninstall.ps1` and the Start Menu shortcut all work the same either way.

## The directory hazard

`%LOCALAPPDATA%\beyondMeetings` and `%LOCALAPPDATA%\beyondmeetings` differ
only in case. Windows paths are case-insensitive, so **they are the same
directory**: the program and every recording the user has ever made live side
by side in it.

The program therefore installs into an `app` subdirectory, and the
uninstaller removes only that subdirectory and the two files it put in `bin`.
Pointing `{app}` one level higher would make "uninstall" mean "delete every
meeting you recorded". `tests/test_windows_setup_exe.py` asserts this, and the
CI job plants a recording before uninstalling and checks it is still there.

## Building it

CI does this on every push — see `.github/workflows/windows-installer.yml`.
By hand, on 64-bit Windows:

```powershell
python installer\windows\build_payload.py --out build\windows\payload
choco install innosetup -y
& "C:\Program Files (x86)\Inno Setup 6\ISCC.exe" `
    /DAppVersion=0.1.0 `
    "/DPayload=$PWD\build\windows\payload" `
    "/O$PWD\dist" `
    installer\windows\beyondmeetings.iss
```

Build it on Windows. `pip wheel` picks wheels for the platform it runs on, so
a Linux build would quietly bundle manylinux wheels that cannot be imported.

To test the result without clicking through the wizard:

```powershell
.\dist\beyondMeetings-Setup-x64.exe /VERYSILENT /SUPPRESSMSGBOXES /LOG=install.log
```

Two logs are worth reading afterwards: Inno's, at whatever `/LOG=` named, and
`setup-finish.ps1`'s, at `%TEMP%\beyondmeetings-setup.log`.
