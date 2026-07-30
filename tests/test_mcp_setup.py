import json

import pytest

from beyondmeetings.mcp_setup import (
    AGENTS, detect_agents, register_mcp, server_definition,
)


def test_server_definition_scopes_the_filesystem_server_to_the_vault():
    spec = server_definition("/home/x/Vault")
    assert spec["command"] == "npx"
    assert "/home/x/Vault" in spec["args"]


def test_detect_reports_only_installed_agents(monkeypatch):
    monkeypatch.setattr(
        "shutil.which", lambda n: "/usr/bin/claude" if n == "claude" else None
    )
    assert detect_agents() == ["claude"]


def test_claude_registration_creates_config_when_absent(tmp_path):
    register_mcp("claude", "/v", home=tmp_path)
    data = json.loads((tmp_path / ".claude.json").read_text())
    assert "beyondmeetings-vault" in data["mcpServers"]


def test_claude_registration_preserves_unrelated_keys(tmp_path):
    """The real ~/.claude.json holds the user's entire Claude Code setup."""
    target = tmp_path / ".claude.json"
    target.write_text(json.dumps({
        "numStartups": 42,
        "projects": {"/some/path": {"history": ["a", "b"]}},
        "mcpServers": {"existing": {"command": "foo"}},
    }))
    register_mcp("claude", "/v", home=tmp_path)
    data = json.loads(target.read_text())
    assert data["numStartups"] == 42
    assert data["projects"]["/some/path"]["history"] == ["a", "b"]
    assert "existing" in data["mcpServers"]
    assert "beyondmeetings-vault" in data["mcpServers"]


def test_claude_registration_writes_a_backup(tmp_path):
    target = tmp_path / ".claude.json"
    target.write_text('{"numStartups": 7}')
    register_mcp("claude", "/v", home=tmp_path)
    backup = json.loads((tmp_path / ".claude.json.bak").read_text())
    assert backup["numStartups"] == 7
    assert "mcpServers" not in backup


def test_registration_is_idempotent(tmp_path):
    register_mcp("claude", "/v", home=tmp_path)
    register_mcp("claude", "/v", home=tmp_path)
    servers = json.loads((tmp_path / ".claude.json").read_text())["mcpServers"]
    assert len(servers) == 1


def test_re_registration_updates_the_vault_path(tmp_path):
    register_mcp("claude", "/old", home=tmp_path)
    register_mcp("claude", "/new", home=tmp_path)
    servers = json.loads((tmp_path / ".claude.json").read_text())["mcpServers"]
    assert "/new" in servers["beyondmeetings-vault"]["args"]
    assert "/old" not in servers["beyondmeetings-vault"]["args"]


def test_corrupt_existing_config_is_refused_not_overwritten(tmp_path):
    target = tmp_path / ".claude.json"
    target.write_text("{ this is not json")
    with pytest.raises(ValueError, match="could not be parsed"):
        register_mcp("claude", "/v", home=tmp_path)
    assert target.read_text() == "{ this is not json"


def test_no_temp_file_is_left_behind(tmp_path):
    register_mcp("claude", "/v", home=tmp_path)
    assert not list(tmp_path.glob("*.tmp"))


def test_gemini_registration_uses_its_settings_file(tmp_path):
    register_mcp("gemini", "/v", home=tmp_path)
    data = json.loads((tmp_path / ".gemini" / "settings.json").read_text())
    assert "beyondmeetings-vault" in data["mcpServers"]


def test_codex_registration_uses_toml(tmp_path):
    register_mcp("codex", "/v", home=tmp_path)
    text = (tmp_path / ".codex" / "config.toml").read_text()
    assert "mcp_servers.beyondmeetings-vault" in text
    assert "/v" in text


def test_codex_registration_preserves_existing_toml(tmp_path):
    config = tmp_path / ".codex" / "config.toml"
    config.parent.mkdir()
    config.write_text('model = "o3"\n')
    register_mcp("codex", "/v", home=tmp_path)
    assert 'model = "o3"' in config.read_text()


def test_codex_re_registration_does_not_stack_blocks(tmp_path):
    register_mcp("codex", "/v", home=tmp_path)
    register_mcp("codex", "/v", home=tmp_path)
    text = (tmp_path / ".codex" / "config.toml").read_text()
    assert text.count("mcp_servers.beyondmeetings-vault") == 1


def test_unknown_agent_raises():
    with pytest.raises(ValueError, match="unknown agent"):
        register_mcp("emacs", "/v")


def test_every_declared_agent_has_a_writer():
    for name in AGENTS:
        assert AGENTS[name]["writer"] is not None
        assert AGENTS[name]["label"]
