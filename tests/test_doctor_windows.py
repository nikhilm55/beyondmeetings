"""Windows doctor rows.

These exist so `beyondmeetings doctor` can repair Windows integration. Before
this, the Start Menu shortcut was written by install.ps1 alone, so a missing
one was invisible to the wizard and unfixable without reinstalling.
"""
from beyondmeetings.desktop_windows import shortcut_path, startup_shortcut_path
from beyondmeetings.doctor import windows as win
from beyondmeetings.provision_windows import Outcome


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


# --- the WebView2 runtime row -----------------------------------------------
#
# This had no test of its own, which is how fix() came to report failure after
# a successful install: the bootstrapper exits 0 while the runtime is still
# being laid down, so detect() alone is the wrong answer to "did the fix work".

def test_webview2_is_ok_when_the_runtime_is_registered(monkeypatch):
    monkeypatch.setattr(
        "beyondmeetings.doctor.windows.registry_version", lambda: "121.0.2277.128"
    )
    result = win.WebView2Check().detect()

    assert result.status == "ok"
    assert "121.0.2277.128" in result.detail


def test_webview2_missing_points_at_the_browser_fallback(monkeypatch):
    monkeypatch.setattr("beyondmeetings.doctor.windows.registry_version", lambda: None)
    result = win.WebView2Check().detect()

    assert result.status == "missing"
    assert "127.0.0.1:7788" in result.detail


def test_webview2_is_not_required_because_a_browser_works(monkeypatch):
    assert win.WebView2Check().required is False
    assert win.WebView2Check().fixable is True


def test_webview2_fix_does_not_call_a_working_install_a_failure(monkeypatch):
    """The bootstrapper returns before the registry catches up."""
    monkeypatch.setattr(
        "beyondmeetings.doctor.windows.ensure_webview2",
        lambda: Outcome("WebView2 runtime", "installed", "installed"),
    )
    monkeypatch.setattr("beyondmeetings.doctor.windows.registry_version", lambda: None)

    result = win.WebView2Check().fix()

    assert result.status == "ok"
    assert "restart" in result.detail.lower()


def test_webview2_fix_reports_a_real_failure(monkeypatch):
    monkeypatch.setattr(
        "beyondmeetings.doctor.windows.ensure_webview2",
        lambda: Outcome("WebView2 runtime", "failed", "no network"),
    )
    result = win.WebView2Check().fix()

    assert result.status == "missing"
    assert "no network" in result.detail


def test_webview2_fix_reports_the_version_once_the_registry_has_it(monkeypatch):
    monkeypatch.setattr(
        "beyondmeetings.doctor.windows.ensure_webview2",
        lambda: Outcome("WebView2 runtime", "installed", "121.0"),
    )
    monkeypatch.setattr("beyondmeetings.doctor.windows.registry_version", lambda: "121.0")

    assert win.WebView2Check().fix().status == "ok"
