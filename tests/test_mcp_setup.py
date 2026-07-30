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
    register_mcp("claude", "/v", home=tmp_path, use_cli=False)
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
    register_mcp("claude", "/v", home=tmp_path, use_cli=False)
    data = json.loads(target.read_text())
    assert data["numStartups"] == 42
    assert data["projects"]["/some/path"]["history"] == ["a", "b"]
    assert "existing" in data["mcpServers"]
    assert "beyondmeetings-vault" in data["mcpServers"]


def test_claude_registration_writes_a_backup(tmp_path):
    target = tmp_path / ".claude.json"
    target.write_text('{"numStartups": 7}')
    register_mcp("claude", "/v", home=tmp_path, use_cli=False)
    backup = json.loads((tmp_path / ".claude.json.bak").read_text())
    assert backup["numStartups"] == 7
    assert "mcpServers" not in backup


def test_registration_is_idempotent(tmp_path):
    register_mcp("claude", "/v", home=tmp_path, use_cli=False)
    register_mcp("claude", "/v", home=tmp_path, use_cli=False)
    servers = json.loads((tmp_path / ".claude.json").read_text())["mcpServers"]
    assert len(servers) == 1


def test_re_registration_updates_the_vault_path(tmp_path):
    register_mcp("claude", "/old", home=tmp_path, use_cli=False)
    register_mcp("claude", "/new", home=tmp_path, use_cli=False)
    servers = json.loads((tmp_path / ".claude.json").read_text())["mcpServers"]
    assert "/new" in servers["beyondmeetings-vault"]["args"]
    assert "/old" not in servers["beyondmeetings-vault"]["args"]


def test_corrupt_existing_config_is_refused_not_overwritten(tmp_path):
    target = tmp_path / ".claude.json"
    target.write_text("{ this is not json")
    with pytest.raises(ValueError, match="could not be parsed"):
        register_mcp("claude", "/v", home=tmp_path, use_cli=False)
    assert target.read_text() == "{ this is not json"


def test_no_temp_file_is_left_behind(tmp_path):
    register_mcp("claude", "/v", home=tmp_path, use_cli=False)
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


# --- Review finding #6: permissions, symlinks, fsync, backup ---

def test_permissions_are_preserved_not_downgraded(tmp_path):
    """A 0600 config used to come back 0644 after registration."""
    import os
    import stat

    target = tmp_path / ".claude.json"
    target.write_text('{"numStartups": 1}')
    os.chmod(target, 0o600)
    register_mcp("claude", "/v", home=tmp_path, use_cli=False)
    assert stat.S_IMODE(target.stat().st_mode) == 0o600


def test_a_symlinked_config_is_followed_not_replaced(tmp_path):
    """A dotfiles-managed config must keep its symlink."""
    real = tmp_path / "dotfiles" / "claude.json"
    real.parent.mkdir()
    real.write_text('{"numStartups": 3}')
    link = tmp_path / ".claude.json"
    link.symlink_to(real)

    register_mcp("claude", "/v", home=tmp_path, use_cli=False)

    assert link.is_symlink(), "the symlink was replaced with a regular file"
    assert "beyondmeetings-vault" in json.loads(real.read_text())["mcpServers"]


def test_the_pristine_backup_is_not_overwritten_by_a_second_run(tmp_path):
    target = tmp_path / ".claude.json"
    target.write_text('{"numStartups": 9}')
    register_mcp("claude", "/v", home=tmp_path, use_cli=False)
    register_mcp("claude", "/w", home=tmp_path, use_cli=False)
    backup = json.loads((tmp_path / ".claude.json.bak").read_text())
    assert "mcpServers" not in backup, "backup should still be the original"
    assert backup["numStartups"] == 9


def test_claude_cli_is_preferred_when_available(monkeypatch, tmp_path):
    """Claude Code rewrites its config from memory; let it serialise its own."""
    calls = []
    monkeypatch.setattr(
        "shutil.which", lambda n: "/usr/bin/claude" if n == "claude" else None
    )

    class Result:
        returncode = 0

    monkeypatch.setattr(
        "subprocess.run", lambda *a, **k: calls.append(a[0]) or Result()
    )
    register_mcp("claude", "/v", home=tmp_path)
    assert calls and "mcp" in calls[0] and "/v" in calls[0]
    assert not (tmp_path / ".claude.json").exists(), "should not have written a file"


def test_falls_back_to_the_file_when_the_cli_fails(monkeypatch, tmp_path):
    monkeypatch.setattr(
        "shutil.which", lambda n: "/usr/bin/claude" if n == "claude" else None
    )

    class Result:
        returncode = 1

    monkeypatch.setattr("subprocess.run", lambda *a, **k: Result())
    register_mcp("claude", "/v", home=tmp_path)
    assert "beyondmeetings-vault" in json.loads(
        (tmp_path / ".claude.json").read_text()
    )["mcpServers"]
