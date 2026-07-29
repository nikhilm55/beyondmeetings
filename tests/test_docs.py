from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_readme_exists_and_shows_the_install_command():
    text = (ROOT / "README.md").read_text()
    assert "install.sh" in text
    assert "beyondmeetings start" in text


def test_readme_states_the_linux_only_limitation():
    assert "Linux only" in (ROOT / "README.md").read_text()


def test_readme_documents_the_providers():
    text = (ROOT / "README.md").read_text()
    for provider in ("Claude", "ChatGPT", "Gemini", "Ollama"):
        assert provider in text


def test_readme_discloses_what_leaves_the_machine():
    text = (ROOT / "README.md").read_text()
    assert "Privacy" in text
    assert "sent to Groq" in text


def test_license_is_present_and_not_a_placeholder():
    text = (ROOT / "LICENSE").read_text()
    assert "MIT" in text
    assert "REPLACE" not in text


def test_contributing_documents_the_clone_path_and_tests():
    text = (ROOT / "CONTRIBUTING.md").read_text()
    assert "git clone" in text
    assert "pytest" in text


def test_contributing_explains_how_to_add_a_provider():
    assert "LLMProvider" in (ROOT / "CONTRIBUTING.md").read_text()
