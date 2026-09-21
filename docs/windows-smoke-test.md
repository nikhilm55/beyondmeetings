# Windows smoke test

CI runs the whole test suite on `windows-latest`, which catches import errors,
path bugs and packaging mistakes. It cannot catch anything below.

GitHub's Windows runners have no audio endpoint, no interactive desktop session
and no login cycle, so **WASAPI capture, the tray icon, the Start Menu shortcut
and start-at-login are untested until a human runs them once.** This file is
that run. Everything here is Windows 11.

Report results by editing the Status column and opening an issue for anything
that fails.

## 0. The bare machine

**Run section 1 on a Windows VM with nothing installed on it**, not on a
development box. This is not optional polish: the installer once required git,
because `pip install … @ git+<url>` shells out to it. That passed on every
developer machine and every CI runner, and failed on the only kind of machine
a new user has. CI now hides git from `PATH` for one step, which catches that
specific bug — but only that one.

A clean VM is the only place the rows below mean anything. Snapshot it before
installing so you can repeat the run.

| # | Expected | Status |
|---|---|---|
| 0.1 | No Python, no git, no ffmpeg on the VM before you start | |
| 0.2 | Section 1 completes anyway, without you installing anything by hand | |
| 0.3 | Nothing prompts for admin (no UAC dialog at any point) | |
| 0.4 | `%TEMP%\beyondmeetings-install.log` exists afterwards and reads sensibly | |

## 1. Install from one line

Open PowerShell (no admin needed):

```powershell
irm -useb https://raw.githubusercontent.com/nikhilm55/beyondmeetings/main/install.ps1 | iex
```

| # | Expected | Status |
|---|---|---|
| 1.1 | No execution-policy error, and no `.ps1` left in the current directory | |
| 1.2 | Reports the Python it chose, or that it fell back to uv | |
| 1.3 | Creates `%LOCALAPPDATA%\beyondMeetings\app\venv` | |
| 1.4 | Reports a row each for ffmpeg and the WebView2 runtime | |
| 1.5 | `%LOCALAPPDATA%\beyondMeetings\bin\ffmpeg.exe` exists, or ffmpeg is on `PATH` | |
| 1.6 | Says it added the Start Menu shortcut | |
| 1.7 | The setup window opens on its own | |
| 1.8 | Exits 0 — `$LASTEXITCODE` is 0, and `install.cmd` does not print "Installation failed" | |

If the machine has **no** Python at all, 1.2 must fall back to uv and still
reach 1.7.

Then pull the plug and do it again. With the VM's network disabled after the
venv exists, 1.4 must report ffmpeg as missing and the install must still
reach 1.8 — a prerequisite that cannot be fetched is a reported row, never a
failed installation.

## 2. The command works

```powershell
& "$env:LOCALAPPDATA\beyondMeetings\bin\beyondmeetings.cmd" doctor
```

| # | Expected | Status |
|---|---|---|
| 2.1 | `doctor` prints rows, not a traceback | |
| 2.2 | A `Windows audio capture` row reports ok | |
| 2.3 | An `App icon` row reports ok | |
| 2.4 | A `Start at login` row reports **missing** (installing must not silently opt you in) | |
| 2.5 | Fixing `Start at login` from the wizard makes it ok | |
| 2.6 | An `ffmpeg` row reports ok | |
| 2.7 | An `App window runtime` row reports ok | |
| 2.8 | Deleting `bin\ffmpeg.exe`, then fixing the `ffmpeg` row, downloads it again | |

2.8 is the other half of section 0: whatever the installer could not fetch,
`doctor` has to be able to fetch later, through the same code.

## 3. Record something real

Join any call — or just play a YouTube video, which exercises the same loopback
path — and record 30 seconds while also speaking.

| # | Expected | Status |
|---|---|---|
| 3.1 | Recording starts without a UAC prompt | |
| 3.2 | A tray icon appears and shows recording state | |
| 3.3 | Stopping produces a WAV under `%LOCALAPPDATA%\beyondmeetings\recordings\<date>\` | |
| 3.4 | **Both** sides are audible: the video/other participants *and* your microphone | |
| 3.5 | The WAV opens in Media Player, i.e. its header is valid | |
| 3.6 | Transcription completes and a note is written to the library | |

3.4 is the single most important line in this document. It is the whole reason
the Windows backend exists, and it is the one thing no CI can check.

## 4. A long meeting rolls over

Set `segment_minutes` low (2 or 3) in `config.toml`, then record past it.

| # | Expected | Status |
|---|---|---|
| 4.1 | A second `_seg001.wav` appears without a gap in audio | |
| 4.2 | Killing the app mid-segment still leaves a playable WAV | |

## 5. Start at login

Enable `Start at login`, reboot.

| # | Expected | Status |
|---|---|---|
| 5.1 | **No black console window flashes** at login | |
| 5.2 | The tray icon is present after logging in | |
| 5.3 | It appears in Task Manager → Startup, so it is removable the normal way | |

5.1 is why the shortcut targets `pythonw.exe -m beyondmeetings` instead of the
console entry point.

## 6. Uninstall keeps your meetings

```powershell
& ([scriptblock]::Create((irm -useb https://raw.githubusercontent.com/nikhilm55/beyondmeetings/main/uninstall.ps1))) -DryRun
```

| # | Expected | Status |
|---|---|---|
| 6.1 | `-DryRun` lists removals and changes nothing | |
| 6.2 | A real run removes the app, shim and both shortcuts | |
| 6.3 | `%LOCALAPPDATA%\beyondmeetings\recordings` **still exists** | |
| 6.4 | Your notes library is untouched | |
| 6.5 | `-PurgeData` does remove recordings when asked | |
| 6.6 | A bundled `bin\ffmpeg.exe` is removed, but an ffmpeg you installed yourself is not | |

6.3 matters more than it looks: on Windows the config directory resolves to the
same path as the data directory, so a careless uninstaller would delete
recordings while "clearing settings".

## 7. Wrong-shell guards

| # | Command | Expected | Status |
|---|---|---|---|
| 7.1 | `curl -fsSL <install.sh> \| bash` in **Git Bash** | Refuses, prints the PowerShell line, creates nothing | |
| 7.2 | Same command in **WSL** | Refuses, mentions `BEYONDMEETINGS_ALLOW_WSL=1` | |
| 7.3 | `curl … \| BEYONDMEETINGS_ALLOW_WSL=1 bash` in WSL | Proceeds with the Linux install | |

The variable goes on `bash`, not on `curl`. `VAR=1 curl … | bash` sets it for
the download process only, so the installer never sees it and 7.3 would fail.
