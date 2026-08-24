"""Windows doctor rows.

These exist so `beyondmeetings doctor` can repair Windows integration. Before
this, the Start Menu shortcut was written by install.ps1 alone, so a missing
one was invisible to the wizard and unfixable without reinstalling.
"""
from beyondmeetings.desktop_windows import shortcut_path, startup_shortcut_path
from beyondmeetings.doctor import windows as win


def test_the_launcher_row_is_missing_until_a_shortcut_exists(tmp_path):
    check = win.StartMenuShortcutCheck(home=tmp_path)
    assert check.detect().status == "missing"

    link = shortcut_path(tmp_path)
    link.parent.mkdir(parents=True, exist_ok=True)
    link.touch()
    result = check.detect()
    assert result.status == "ok"
    assert str(link) in result.detail


def test_the_autostart_row_is_missing_until_the_startup_link_exists(tmp_path):
    check = win.WindowsAutostartCheck(home=tmp_path)
    assert check.detect().status == "missing"

    link = startup_shortcut_path(tmp_path)
    link.parent.mkdir(parents=True, exist_ok=True)
    link.touch()
    assert check.detect().status == "ok"


def test_fixing_the_launcher_installs_the_shortcut(tmp_path, monkeypatch):
    calls = []

    def fake_install(home=None):
        calls.append(home)
        link = shortcut_path(home)
        link.parent.mkdir(parents=True, exist_ok=True)
        link.touch()

    monkeypatch.setattr(win, "install_shortcut", fake_install)
    check = win.StartMenuShortcutCheck(home=tmp_path)

    assert check.fixable
    assert check.fix().status == "ok"
    assert calls == [tmp_path]


def test_fixing_autostart_installs_the_startup_shortcut(tmp_path, monkeypatch):
    def fake_install(home=None):
        link = startup_shortcut_path(home)
        link.parent.mkdir(parents=True, exist_ok=True)
        link.touch()

    monkeypatch.setattr(win, "install_startup_shortcut", fake_install)
    check = win.WindowsAutostartCheck(home=tmp_path)

    assert check.fixable
    assert check.fix().status == "ok"


def test_neither_row_is_required_so_a_refusal_cannot_block_setup(tmp_path):
    # Recording must not depend on shell integration succeeding.
    assert win.StartMenuShortcutCheck(home=tmp_path).required is False
    assert win.WindowsAutostartCheck(home=tmp_path).required is False
    assert win.WindowsAudioCheck().required is True
