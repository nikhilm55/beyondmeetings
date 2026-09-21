"""Windows Start Menu and login shortcuts.

Writing a .lnk needs the Windows shell, so the module hands a PowerShell
snippet to an injectable runner. That makes everything up to the shell call
testable here: where the shortcut is placed, what the shell is told to put in
it, and whether paths that need escaping survive. What cannot be tested without
Windows is whether the shell then produces a working link.
"""
from pathlib import Path

from beyondmeetings.desktop_windows import (
    SHORTCUT_NAME,
    WINDOW_MINIMIZED,
    build_shortcut_script,
    install_shortcut,
    install_startup_shortcut,
    remove_shortcut,
    remove_startup_shortcut,
    shortcut_path,
    start_menu_dir,
    startup_shortcut_path,
)


class Runner:
    def __init__(self):
        self.scripts = []

    def run(self, script):
        self.scripts.append(script)


def test_the_shortcut_lands_in_the_start_menu_programs_folder(tmp_path):
    assert start_menu_dir(tmp_path) == (
        tmp_path / "AppData" / "Roaming" / "Microsoft" / "Windows"
        / "Start Menu" / "Programs"
    )
    assert shortcut_path(tmp_path).name == SHORTCUT_NAME


def test_the_login_shortcut_goes_in_the_startup_subfolder(tmp_path):
    assert startup_shortcut_path(tmp_path).parent == (
        start_menu_dir(tmp_path) / "Startup"
    )


def test_appdata_env_var_wins_when_no_home_is_given(tmp_path, monkeypatch):
    monkeypatch.setenv("APPDATA", str(tmp_path / "roaming"))
    assert str(shortcut_path()).startswith(str(tmp_path / "roaming"))


def test_installing_asks_the_shell_for_a_shortcut_to_the_app_command(tmp_path):
    runner = Runner()
    target = Path("C:/bm.exe")
    # windowed explicitly: which route is chosen otherwise depends on whether
    # pywebview is installed *here*, which would make this test's meaning
    # depend on the machine running it.
    link = install_shortcut(
        home=tmp_path, runner=runner, target=target, windowed=True
    )

    assert link == shortcut_path(tmp_path)
    script = runner.scripts[0]
    assert f"$link.TargetPath = '{target}'" in script
    assert "$link.Arguments = 'app'" in script
    assert str(link) in script


def test_a_browser_only_install_gets_a_shortcut_that_opens_the_browser(tmp_path):
    runner = Runner()
    install_shortcut(home=tmp_path, runner=runner, windowed=False)

    script = runner.scripts[0]
    assert "$link.Arguments = '-m beyondmeetings open'" in script


def test_the_login_shortcut_runs_the_server_windowless(tmp_path):
    runner = Runner()
    target = Path("C:/py/pythonw.exe")
    install_startup_shortcut(home=tmp_path, runner=runner, target=target)

    script = runner.scripts[0]
    assert f"$link.TargetPath = '{target}'" in script
    assert "-m beyondmeetings serve --no-browser" in script
    # A console entry point here would flash a black window at every login.
    assert "beyondmeetings.exe" not in script
    assert f"$link.WindowStyle = {WINDOW_MINIMIZED}" in script


def test_the_script_creates_the_folder_before_saving(tmp_path):
    script = build_shortcut_script(
        tmp_path / "sub" / "x.lnk", Path("C:/bm.exe")
    )
    assert "New-Item -ItemType Directory" in script
    assert script.index("New-Item") < script.index("$link.Save()")


def test_quotes_in_a_username_cannot_break_out_of_the_script():
    # C:\Users\O'Brien is a legal Windows path; unescaped it ends the string.
    link = Path("C:/Users/O'Brien/x.lnk")
    script = build_shortcut_script(link, Path("C:/bm.exe"))
    # Built from the Path so the assertion holds on both path flavours; the
    # point is the doubled quote, not the separator.
    assert "'" + str(link).replace("'", "''") + "'" in script
    assert "O''Brien" in script


def test_removing_a_missing_shortcut_is_not_an_error(tmp_path):
    remove_shortcut(tmp_path)
    remove_startup_shortcut(tmp_path)

    link = shortcut_path(tmp_path)
    link.parent.mkdir(parents=True, exist_ok=True)
    link.touch()
    remove_shortcut(tmp_path)
    assert not link.exists()


# --- what the app icon starts -------------------------------------------------
#
# The setup.exe ships no pywebview: its app runs in a browser, so the WebView2
# runtime a native window would need is one more thing to fetch on a machine
# that may not be able to. install.ps1 does ship it. One shortcut has to be
# right for both, and `doctor` repairs it on either.

import subprocess  # noqa: E402
import sys  # noqa: E402

from beyondmeetings.desktop import (  # noqa: E402
    detach_flags, resolve_executable, server_log_dir,
)
from beyondmeetings.desktop_windows import (  # noqa: E402
    ICON, have_app_window, launch_target,
)


def test_a_windowed_install_keeps_opening_the_native_window():
    target, arguments = launch_target(windowed=True)

    assert target.name == "beyondmeetings.exe"
    assert arguments == "app"


def test_a_browser_only_install_opens_the_browser_instead():
    target, arguments = launch_target(windowed=False)

    assert target.name in {"pythonw.exe", Path(sys.executable).name}
    assert arguments == "-m beyondmeetings open"


def test_open_not_serve_because_clicking_twice_must_not_fail():
    """`serve` binds the port itself, so a second click dies on it. `open`
    connects to the server that is already there."""
    _, arguments = launch_target(windowed=False)

    assert "serve" not in arguments


def test_the_window_route_is_chosen_by_whether_pywebview_is_installed():
    assert have_app_window(find_spec=lambda name: object()) is True
    assert have_app_window(find_spec=lambda name: None) is False


def test_a_broken_import_system_is_not_a_window():
    def explode(name):
        raise ValueError("__spec__ is not set")

    assert have_app_window(find_spec=explode) is False


def test_the_shortcut_carries_the_application_icon():
    script = build_shortcut_script(
        Path("C:/link.lnk"), Path("C:/pythonw.exe"), icon=Path("C:/app/icon.ico")
    )

    assert "$link.IconLocation = 'C:/app/icon.ico'" in script


def test_an_icon_free_shortcut_sets_no_icon_location():
    script = build_shortcut_script(Path("C:/link.lnk"), Path("C:/pythonw.exe"))

    assert "IconLocation" not in script


def test_the_icon_ships_inside_the_package():
    """Not read from a checkout: a setup.exe user has no repository, and the
    .lnk holds a path that has to keep resolving after the installer exits."""
    assert ICON.is_file()
    assert ICON.read_bytes()[:4] == b"\x00\x00\x01\x00", "not a Windows .ico"


# --- finding and detaching the server -------------------------------------------


def test_the_windows_command_is_the_exe_beside_the_interpreter():
    """A bare `beyondmeetings` is not a file on Windows, so the old fallback
    returned a POSIX path that could not exist there."""
    found = resolve_executable(platform="win32")

    assert found.endswith("beyondmeetings.exe")
    assert Path(found).is_absolute()


def test_the_command_shim_is_never_handed_to_createprocess(monkeypatch, tmp_path):
    """Both installers put a beyondmeetings.cmd on disk. CreateProcess cannot
    run a batch file, so a PATH hit on one would be worse than no hit."""
    shim = tmp_path / "beyondmeetings.cmd"
    shim.write_text("@echo off\n", encoding="utf-8")
    monkeypatch.setattr("shutil.which", lambda name: str(shim))

    assert not resolve_executable(platform="win32").endswith(".cmd")


def test_the_log_directory_exists_on_the_platform_it_names(monkeypatch, tmp_path):
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))

    assert server_log_dir("win32") == tmp_path / "beyondmeetings" / "logs"
    assert server_log_dir("linux").parts[-3:] == (".local", "share", "beyondmeetings")


def test_detaching_is_a_no_op_off_windows():
    assert detach_flags("linux") == 0
    assert detach_flags("darwin") == 0


def test_windows_gets_flags_that_actually_detach(monkeypatch):
    """start_new_session is POSIX-only — subprocess ignores it on Windows, so
    the server was a child of a launcher about to exit."""
    monkeypatch.setattr(subprocess, "DETACHED_PROCESS", 0x8, raising=False)
    monkeypatch.setattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0x200, raising=False)
    monkeypatch.setattr(subprocess, "CREATE_NO_WINDOW", 0x8000000, raising=False)

    assert detach_flags("win32") == 0x8 | 0x200 | 0x8000000


# --- reporting a failure with nowhere to print it -----------------------------


def test_a_console_session_reports_the_ordinary_way(monkeypatch):
    """There is a stderr to print to, so no dialog should appear."""
    from beyondmeetings.desktop import report_headless

    shown = []
    assert report_headless("boom", platform="win32", box=lambda *a: shown.append(a)) \
        is False
    assert shown == []


def test_a_windowless_session_gets_a_message_box(monkeypatch):
    from beyondmeetings.desktop import report_headless

    monkeypatch.setattr("sys.stdout", None)
    shown = []

    assert report_headless("boom", platform="win32", box=lambda *a: shown.append(a))
    assert shown[0][1] == "boom"


def test_nothing_is_shown_off_windows(monkeypatch):
    from beyondmeetings.desktop import report_headless

    monkeypatch.setattr("sys.stdout", None)

    assert report_headless("boom", platform="linux", box=lambda *a: None) is False


def test_a_failure_to_report_a_failure_is_not_an_exception(monkeypatch):
    from beyondmeetings.desktop import report_headless

    monkeypatch.setattr("sys.stdout", None)

    def explode(*args):
        raise OSError("no window station")

    assert report_headless("boom", platform="win32", box=explode) is False
