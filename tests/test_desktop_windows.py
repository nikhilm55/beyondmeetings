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
    link = install_shortcut(home=tmp_path, runner=runner, target=Path("C:/bm.exe"))

    assert link == shortcut_path(tmp_path)
    script = runner.scripts[0]
    assert "$link.TargetPath = 'C:/bm.exe'" in script
    assert "$link.Arguments = 'app'" in script
    assert str(link) in script


def test_the_login_shortcut_runs_the_server_windowless(tmp_path):
    runner = Runner()
    install_startup_shortcut(
        home=tmp_path, runner=runner, target=Path("C:/py/pythonw.exe")
    )

    script = runner.scripts[0]
    assert "$link.TargetPath = 'C:/py/pythonw.exe'" in script
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
    script = build_shortcut_script(
        Path("C:/Users/O'Brien/x.lnk"), Path("C:/bm.exe")
    )
    assert "'C:/Users/O''Brien/x.lnk'" in script


def test_removing_a_missing_shortcut_is_not_an_error(tmp_path):
    remove_shortcut(tmp_path)
    remove_startup_shortcut(tmp_path)

    link = shortcut_path(tmp_path)
    link.parent.mkdir(parents=True, exist_ok=True)
    link.touch()
    remove_shortcut(tmp_path)
    assert not link.exists()
