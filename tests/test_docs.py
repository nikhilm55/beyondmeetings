import pytest
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_readme_exists_and_shows_the_install_command():
    text = (ROOT / "README.md").read_text(encoding="utf-8")
    assert "install.sh" in text
    assert "beyondmeetings start" in text


def test_readme_discloses_platform_support():
    text = (ROOT / "README.md").read_text(encoding="utf-8")
    assert "Platform support" in text
    assert "PipeWire" in text, "the Linux capture requirement must be stated"


def test_readme_does_not_claim_macos_is_verified():
    """macOS is implemented but has never been run on a Mac.

    Whoever installs it first is doing the shakedown run, and has to know that
    before they start rather than after a meeting fails to record. This test
    exists so the warning cannot quietly disappear in a later edit.
    """
    # Normalised: the warning must survive reflowing and bold markers, so the
    # test checks what it says rather than how it happens to be wrapped.
    text = " ".join((ROOT / "README.md").read_text(encoding="utf-8").replace("**", "").split())

    assert "not yet verified on hardware" in text
    assert "never been run on a Mac" in text


def test_readme_documents_the_providers():
    text = (ROOT / "README.md").read_text(encoding="utf-8")
    for provider in ("Claude", "ChatGPT", "Gemini", "Ollama"):
        assert provider in text


def test_readme_discloses_what_leaves_the_machine():
    text = (ROOT / "README.md").read_text(encoding="utf-8")
    assert "Privacy" in text
    assert "sent to Groq" in text


def test_license_is_present_and_not_a_placeholder():
    text = (ROOT / "LICENSE").read_text(encoding="utf-8")
    assert "MIT" in text
    assert "REPLACE" not in text


def test_contributing_documents_the_clone_path_and_tests():
    text = (ROOT / "CONTRIBUTING.md").read_text(encoding="utf-8")
    assert "git clone" in text
    assert "pytest" in text


def test_contributing_explains_how_to_add_a_provider():
    assert "LLMProvider" in (ROOT / "CONTRIBUTING.md").read_text(encoding="utf-8")


@pytest.mark.skipif(
    sys.platform == "win32", reason="Windows has no executable bit"
)
def test_uninstaller_exists_and_is_executable():
    script = ROOT / "uninstall.sh"
    assert script.is_file()
    assert script.stat().st_mode & 0o111


def test_uninstaller_does_not_delete_data_by_default():
    """Removing the program must never take a user's meetings with it."""
    text = (ROOT / "uninstall.sh").read_text(encoding="utf-8")
    assert "--purge-data" in text
    assert "PURGE_DATA=0" in text


def test_install_prefix_is_not_the_data_directory():
    """A venv inside the data dir makes 'rm -rf' destroy recordings."""
    install = (ROOT / "install.sh").read_text(encoding="utf-8")
    assert "beyondmeetings-app" in install
    assert 'PREFIX="${BEYONDMEETINGS_HOME:-$HOME/.local/share/beyondmeetings}"' not in install


def test_readme_documents_uninstalling():
    assert "## Uninstalling" in (ROOT / "README.md").read_text(encoding="utf-8")


def test_readme_documents_the_app_icon():
    text = (ROOT / "README.md").read_text(encoding="utf-8")
    assert "beyondmeetings open" in text
    assert "icon in your applications" in text
