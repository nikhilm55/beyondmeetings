# Windows 11 support — design

**Date:** 2026-08-24
**Status:** implemented on `fix/windows-support`
**Constraint given:** one-command install from PowerShell, and nothing that
can regress the Linux install, which is in daily use.

## What already existed

PR #4 (`feat/cross-platform-desktop-library`) landed most of the engine work,
so this was not a green field:

- `audio/factory.py` dispatches `win32` → `WindowsRecorder`
- `audio/windows.py` + `audio/windows_worker.py` implement WASAPI loopback and
  microphone capture with segment rollover and valid WAV headers on shutdown
- `config.py` resolves paths through `platformdirs`, so data and config already
  land under `%LOCALAPPDATA%`
- `pyproject.toml` gates `SoundCard` to `sys_platform == "win32"` and
  `pywebview[qt]` to Linux
- `library.py` and `pdf_export.py` branch for `win32`; PDF fonts already fall
  back to `segoeui.ttf` / `arial.ttf`
- `tray.py` falls through to pystray for any non-Ayatana platform
- `doctor/registry.py` had a `windows` flag and a WASAPI check

## The gaps this closes

1. **No Windows one-liner.** The README told Windows users to download the
   project, run `Set-ExecutionPolicy -Scope Process Bypass`, then `.\install.ps1`.
2. **`install.sh` half-installed under Git Bash.** `uname -s` returns
   `MINGW64_NT-*`, which is neither `Darwin` nor `Linux`, so the script fell
   through and then used `venv/bin/python` — a Windows venv has
   `Scripts\python.exe`. It also symlinked and wrote XDG entries, and it failed
   *after* creating directories.
3. **No `desktop_windows.py`.** The Start Menu shortcut lived only inside
   `install.ps1`, so `doctor` could not see or repair Windows integration.
4. **Autostart was XDG-only**, so the Windows tray never survived a reboot.
5. **`install.ps1` lagged `install.sh`**: no venv probe, no uv fallback, no
   already-running check, and no way to call `beyondmeetings` from a terminal.
6. **No `uninstall.ps1`.**
7. **No CI at all**, so nothing guarded either platform.
8. **The test suite read real user data** (found while establishing a
   baseline): `Config()` with an empty `library_path` falls back to
   `DEFAULT_LIBRARY_DIR`, i.e. the developer's actual library. The suite passed
   on a clean checkout and failed on a machine that had recorded a meeting.

## Approach: mirror the macOS pattern, additively

Rejected a `platform/` abstraction layer that would fold `desktop.py` and
`desktop_macos.py` into shared interfaces. It is the nicer end state, but it
rewrites working Linux and macOS code to deliver a Windows feature. Every
change here is either a new file or a new branch guarded by `win32`, so no
Linux code path is edited.

Also rejected doing it all in the installers: it is the smallest diff, but it
leaves `doctor` blind on Windows with no repair path.

### Install contract

`curl … | bash` cannot work in stock PowerShell, which has no `bash`. Rather
than pretend one string works everywhere, each shell gets its idiomatic one:

| Platform | Command |
|---|---|
| Linux / macOS | `curl -fsSL …/install.sh \| bash` |
| Windows | `irm -useb …/install.ps1 \| iex` |

Piping to `iex` writes no file, so the execution-policy step disappears. A
piped script cannot take arguments, so switches use
`& ([scriptblock]::Create((irm -useb <url>))) -DryRun`.

`install.sh` gains one early guard: `MINGW*|MSYS*|CYGWIN*` prints the
PowerShell line and exits 1 before creating anything. WSL is refused the same
way unless `BEYONDMEETINGS_ALLOW_WSL=1`, because PipeWire inside WSL cannot
hear a call running on the Windows host — the install would succeed and then
record silence, which is worse than refusing.

### Shortcuts

`.lnk` is a shell binary format, so writing one means asking Windows. Instead
of adding `pywin32`, `desktop_windows.py` builds a PowerShell snippet and hands
it to an injectable runner — the shape `audio/windows.py` already uses. Two
consequences: no new dependency, and `build_shortcut_script()` is a pure
function, so the logic is unit-tested on Linux CI rather than being
Windows-only dead code.

Paths are single-quoted with `''` escaping, because `C:\Users\O'Brien` is a
legal Windows path.

The login shortcut targets `pythonw.exe -m beyondmeetings serve --no-browser`,
which needs the new two-line `__main__.py`. The console entry point would flash
a black window at every login. `gui-scripts` would also work but changes
packaging metadata that affects the Linux wheel, and this repo has already been
burned by that once (9749b9d).

### Doctor

`doctor/windows.py` gains `StartMenuShortcutCheck` and `WindowsAutostartCheck`,
reusing the Linux ids `launcher` and `autostart` so the wizard renders the same
rows everywhere. `registry.py` grows an `elif windows:` beside the untouched
`if not macos and not windows:`. Both rows are `required = False`: recording
must never depend on shell integration, and a locked-down machine that refuses
COM should still record. Installing refreshes an existing login entry but never
creates one, matching `refresh_installed_autostart` on Linux.

### Uninstall

On Windows `platformdirs` resolves the config directory to the *same path* as
the data directory, so `config.toml` sits inside the folder holding recordings.
`uninstall.ps1` therefore asks Python for the real paths and removes the config
*file*, never the folder, unless `-PurgeData` is given. Same defaults as
`uninstall.sh`: recordings, transcripts and keyring keys are kept.

### Verification

- CI matrix `{ubuntu-latest, windows-latest} × {3.10, 3.12}` running pytest.
  3.10 is the declared floor and the reason `config.py` still carries the
  `tomli`/`tomllib` fallback.
- A separate installer job: `bash -n` plus `--dry-run` on Linux, PowerShell
  `Parser::ParseFile` plus `-DryRun` on Windows. An installer nobody ran is the
  likeliest thing here to be broken, and pytest cannot see it.
- `tests/conftest.py` redirects `XDG_*` and `LOCALAPPDATA`/`APPDATA` to a
  per-session temp directory **at conftest import time**, because `config.py`
  freezes its module-level constants on import. `HOME` is deliberately left
  alone to avoid disturbing tests that legitimately read it.
- Four modules that are platform-bound by nature (`install.sh`, PipeWire,
  `.desktop`, XDG autostart) skip on `win32` only.
- `docs/windows-smoke-test.md` covers what no CI can: real loopback capture,
  the tray, the shortcut, a login cycle, and that uninstall keeps recordings.

## What the first CI run found

The Windows job earned its place immediately. Of 69 failures and 56 errors, the
dominant cause — 168 occurrences — was one real bug:

**`vault/scaffold.py` wrote the Home template without an encoding.** The
template contains `←`, and Windows defaults to cp1252, so
`UnicodeEncodeError: 'charmap' codec can't encode character '\u2190'` fired
before any of the audio work this design is about. A Windows user could not
create a vault at all. Two more sites had the same gap on the read side
(`mcp_setup.py`) and in the Windows recording path itself
(`audio/base.py`, which persists meeting names to the state file).

Every `read_text`/`write_text` in `src/` and `tests/` is now explicit about
encoding. Setting `PYTHONUTF8=1` in CI would have been a one-line alternative
and was rejected: it would have hidden exactly this bug, and would hide the
next one.

The Linux job found a pre-existing failure too: `install.sh` violated
shellcheck's SC1087 (`"$SCRIPT_DIR[desktop]"` reads as an array subscript),
invisible locally because this machine has no shellcheck installed, and the
repo's own test skips when it is absent.

## Review fixes

- **`uninstall.ps1` deleted the program before purging keys**, so `-PurgeKeys`
  always reported "already gone" while `-DryRun` claimed success. The purge now
  runs first, before the Python it depends on is removed.
- **`uninstall.ps1` removed the whole bin directory** with `-Recurse`. Fine for
  the default dedicated path, destructive for anyone who pointed
  `BEYONDMEETINGS_BIN` at a shared `~\bin`. It now removes only its own shim,
  and the directory solely if empty — matching `uninstall.sh`, which removes a
  single symlink.
- **`2>&1 | Out-Null` was unsafe under `$ErrorActionPreference = "Stop"`.** On
  PowerShell 5.1 — what stock Windows 11 ships, and therefore what the `irm`
  line lands in — that turns a native command's stderr into terminating errors.
  Two sites sat outside any try/catch, so a stray warning from the Python child
  would abort the installer after a successful install, before the app opened.
  All are now `2>$null`.
- **The shim was written as ASCII**, mangling a path like `C:\Users\Müller`
  into a broken `.cmd` while the Start Menu shortcut still worked. Now `Oem`.
- **The WSL hint was wrong**: `BEYONDMEETINGS_ALLOW_WSL=1 curl … | bash` sets
  the variable for `curl`, not `bash`. Both the script and the smoke test now
  show `curl … | BEYONDMEETINGS_ALLOW_WSL=1 bash`.
- **The new shortcut tests hardcoded forward slashes.** `Path("C:/bm.exe")`
  stringifies with backslashes on Windows, so three of them could never pass
  there. Expectations are now built from the `Path`.

One review item did not hold up: `pipeline.py:71` was reported as missing an
encoding, but the argument is on line 79 of the same call. `discussion.py` and
`desktop.py` were already explicit too.

## Known limits

- Neither `install.ps1` nor `uninstall.ps1` has been executed. No PowerShell
  exists on the development machine; the first real validation is the CI
  parse-and-dry-run job.
- The suite has never run on Windows before. The first `windows-latest` run may
  surface pre-existing POSIX assumptions beyond the four modules guarded here —
  `test_secrets.py` asserts `0o600` file modes and `test_mcp_setup.py` creates a
  symlink, both of which behave differently on Windows.
- Real capture quality on Windows remains unverified until someone runs
  section 3 of the smoke test.
