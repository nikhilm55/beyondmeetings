import json

from beyondmeetings.config import Config, load_config
from beyondmeetings.doctor.base import run_all
from beyondmeetings.doctor.choices import ProviderChoice, TranscriberChoice
from beyondmeetings.doctor.mcp import McpCheck


def test_provider_choice_offers_keyless_and_keyed_options():
    options = {o["value"] for o in ProviderChoice(Config()).choices}
    assert options == {
        "claude-cli", "codex-cli", "gemini-cli", "ollama",
        "anthropic", "openai", "gemini",
    }


def test_keyless_options_come_first():
    """An API key needs credits; a subscription does not. Lead with those."""
    values = [o["value"] for o in ProviderChoice(Config()).choices]
    first_keyed = values.index("anthropic")
    for keyless in ("claude-cli", "codex-cli", "gemini-cli", "ollama"):
        assert values.index(keyless) < first_keyed


def test_keyed_options_say_they_need_credits():
    for option in ProviderChoice(Config()).choices:
        if option["value"] in ("anthropic", "openai", "gemini"):
            assert "credits" in option["note"] or "quota" in option["note"]


def test_claude_code_is_marked_recommended():
    claude = next(
        o for o in ProviderChoice(Config()).choices if o["value"] == "claude-cli"
    )
    assert claude["recommended"] is True
    assert "No API key" in claude["note"]


def test_only_one_provider_is_recommended():
    assert sum(o["recommended"] for o in ProviderChoice(Config()).choices) == 1


def test_ollama_option_warns_about_code_mixed_speech():
    ollama = next(
        o for o in ProviderChoice(Config()).choices if o["value"] == "ollama"
    )
    assert "Hinglish" in ollama["note"]


def test_provider_choice_is_always_ok():
    """A choice is never a blocker — a default is always selected."""
    assert ProviderChoice(Config()).detect().status == "ok"


def test_provider_choice_reports_the_current_selection():
    assert "Claude" in ProviderChoice(Config(provider="anthropic")).detect().detail


def test_provider_fix_persists_the_selection(tmp_path):
    choice = ProviderChoice(Config(), config_path=tmp_path / "c.toml")
    choice.fix(value="gemini")
    assert load_config(tmp_path / "c.toml").provider == "gemini"


def test_provider_fix_rejects_an_unknown_value(tmp_path):
    choice = ProviderChoice(Config(), config_path=tmp_path / "c.toml")
    assert choice.fix(value="nope").status == "broken"


def test_transcriber_choice_offers_both():
    values = {o["value"] for o in TranscriberChoice(Config()).choices}
    assert values == {"groq", "whispercpp"}


def test_transcriber_fix_persists(tmp_path):
    choice = TranscriberChoice(Config(), config_path=tmp_path / "c.toml")
    choice.fix(value="whispercpp")
    assert load_config(tmp_path / "c.toml").transcriber == "whispercpp"


def test_choices_are_exposed_on_the_row():
    assert len(run_all([ProviderChoice(Config())])[0]["choices"]) == 7


def test_rows_without_choices_expose_an_empty_list():
    from beyondmeetings.doctor.system import FfmpegCheck
    assert run_all([FfmpegCheck()])[0]["choices"] == []


def test_mcp_check_ok_when_no_agent_cli_installed(monkeypatch, tmp_path):
    monkeypatch.setattr("beyondmeetings.doctor.mcp.detect_agents", lambda: [])
    result = McpCheck(Config(vault_path=str(tmp_path)), home=tmp_path, use_cli=False).detect()
    assert result.status == "ok"
    assert "No agent CLI" in result.detail


def test_mcp_check_missing_when_agent_present_but_unregistered(monkeypatch, tmp_path):
    monkeypatch.setattr("beyondmeetings.doctor.mcp.detect_agents", lambda: ["claude"])
    check = McpCheck(Config(vault_path=str(tmp_path)), home=tmp_path, use_cli=False)
    assert check.detect().status == "missing"


def test_mcp_fix_registers_into_each_detected_agent(monkeypatch, tmp_path):
    monkeypatch.setattr("beyondmeetings.doctor.mcp.detect_agents", lambda: ["claude"])
    check = McpCheck(Config(vault_path=str(tmp_path)), home=tmp_path, use_cli=False)
    assert check.fix().status == "ok"
    data = json.loads((tmp_path / ".claude.json").read_text())
    assert "beyondmeetings-vault" in data["mcpServers"]


def test_mcp_check_ok_once_registered(monkeypatch, tmp_path):
    monkeypatch.setattr("beyondmeetings.doctor.mcp.detect_agents", lambda: ["claude"])
    check = McpCheck(Config(vault_path=str(tmp_path)), home=tmp_path, use_cli=False)
    check.fix()
    assert check.detect().status == "ok"


def test_mcp_is_not_required(tmp_path):
    assert McpCheck(Config(), home=tmp_path, use_cli=False).required is False


def test_mcp_fix_without_a_vault_is_refused(monkeypatch, tmp_path):
    monkeypatch.setattr("beyondmeetings.doctor.mcp.detect_agents", lambda: ["claude"])
    assert McpCheck(Config(), home=tmp_path, use_cli=False).fix().status == "broken"


def test_mcp_survives_a_corrupt_agent_config(monkeypatch, tmp_path):
    """A broken config must report unregistered, not crash the wizard."""
    monkeypatch.setattr("beyondmeetings.doctor.mcp.detect_agents", lambda: ["claude"])
    (tmp_path / ".claude.json").write_text("{ not json")
    check = McpCheck(Config(vault_path=str(tmp_path)), home=tmp_path, use_cli=False)
    assert check.detect().status == "missing"
