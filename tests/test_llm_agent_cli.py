"""Agent-CLI providers: inference with no API key.

An API-key-only design excluded everyone on a Claude/ChatGPT/Gemini
subscription — no credits, but working inference already installed.
"""
import pytest

from beyondmeetings.llm.agent_cli import (
    AGENT_COMMANDS, AgentCliError, AgentCliProvider, agent_available, agent_binary,
    resolve_agent_binary,
)
from beyondmeetings.llm.base import ResponseParseError

NOTE_JSON = ('{"title": "Standup", "date": "2026-07-30", '
             '"executive_summary": "We synced."}')


class FakeRun:
    def __init__(self, stdout="", stderr="", returncode=0):
        self.stdout = stdout
        self.stderr = stderr
        self.returncode = returncode


def _patch(monkeypatch, result, calls=None):
    monkeypatch.setattr("shutil.which", lambda n: f"/usr/bin/{n}")

    def fake_run(cmd, **kwargs):
        if calls is not None:
            calls.append((cmd, kwargs))
        return result

    monkeypatch.setattr("subprocess.run", fake_run)


def test_returns_a_parsed_note(monkeypatch):
    _patch(monkeypatch, FakeRun(stdout=NOTE_JSON))
    assert AgentCliProvider("claude-cli").analyse("prompt").title == "Standup"


def test_prompt_goes_over_stdin_not_argv(monkeypatch):
    """An hour-long transcript is far too big for an argv entry."""
    calls = []
    _patch(monkeypatch, FakeRun(stdout=NOTE_JSON), calls)
    AgentCliProvider("claude-cli").analyse("a very long transcript")
    cmd, kwargs = calls[0]
    assert kwargs["input"] == "a very long transcript"
    assert "a very long transcript" not in cmd


def test_uses_the_expected_command(monkeypatch):
    calls = []
    _patch(monkeypatch, FakeRun(stdout=NOTE_JSON), calls)
    AgentCliProvider("claude-cli").analyse("p")
    assert calls[0][0] == ["claude", "-p"]


def test_codex_allows_desktop_runs_outside_a_git_repository(monkeypatch):
    calls = []
    _patch(monkeypatch, FakeRun(stdout=NOTE_JSON), calls)

    AgentCliProvider("codex-cli").analyse("p")

    assert calls[0][0] == ["codex", "exec", "--skip-git-repo-check", "-"]


def test_command_can_be_overridden(monkeypatch):
    calls = []
    _patch(monkeypatch, FakeRun(stdout=NOTE_JSON), calls)
    AgentCliProvider("claude-cli", command=["my-agent", "--go"]).analyse("p")
    assert calls[0][0] == ["my-agent", "--go"]


def test_no_api_key_is_ever_required(monkeypatch):
    """The whole point: this path must not consult secrets at all."""
    _patch(monkeypatch, FakeRun(stdout=NOTE_JSON))

    def explode(*a, **k):
        raise AssertionError("agent CLI must not read a stored key")

    monkeypatch.setattr("beyondmeetings.secrets.get_secret", explode)
    assert AgentCliProvider("claude-cli").analyse("p").title == "Standup"


def test_missing_binary_is_reported_actionably(monkeypatch):
    monkeypatch.setattr("shutil.which", lambda n: None)
    monkeypatch.setattr(
        "beyondmeetings.llm.agent_cli._fallback_agent_binaries", lambda n: []
    )
    with pytest.raises(AgentCliError, match="not installed or discoverable"):
        AgentCliProvider("claude-cli").analyse("p")


def test_finds_a_user_binary_outside_the_desktop_path(tmp_path, monkeypatch):
    binary = tmp_path / ".local" / "bin" / "codex"
    binary.parent.mkdir(parents=True)
    binary.write_text("#!/bin/sh\n")
    binary.chmod(0o755)
    monkeypatch.setattr("pathlib.Path.home", lambda: tmp_path)
    monkeypatch.setattr("shutil.which", lambda n: None)

    assert resolve_agent_binary("codex") == str(binary)


def test_finds_codex_bundled_with_the_openai_editor_extension(tmp_path, monkeypatch):
    binary = (
        tmp_path / ".vscode" / "extensions" / "openai.chatgpt-1.2.3-linux-x64"
        / "bin" / "linux-x86_64" / "codex"
    )
    binary.parent.mkdir(parents=True)
    binary.write_text("#!/bin/sh\n")
    binary.chmod(0o755)
    monkeypatch.setattr("pathlib.Path.home", lambda: tmp_path)
    monkeypatch.setattr("shutil.which", lambda n: None)

    assert resolve_agent_binary("codex") == str(binary)


def test_runs_the_discovered_absolute_binary(tmp_path, monkeypatch):
    binary = tmp_path / ".local" / "bin" / "codex"
    binary.parent.mkdir(parents=True)
    binary.write_text("#!/bin/sh\n")
    binary.chmod(0o755)
    calls = []
    monkeypatch.setattr("pathlib.Path.home", lambda: tmp_path)
    monkeypatch.setattr("shutil.which", lambda n: None)
    monkeypatch.setattr(
        "subprocess.run",
        lambda cmd, **kwargs: calls.append((cmd, kwargs)) or FakeRun(stdout=NOTE_JSON),
    )

    AgentCliProvider("codex-cli").analyse("prompt")

    assert calls[0][0] == [
        str(binary), "exec", "--skip-git-repo-check", "-",
    ]


def test_a_nonzero_exit_mentions_signing_in(monkeypatch):
    _patch(monkeypatch, FakeRun(stderr="not authenticated", returncode=1))
    with pytest.raises(AgentCliError, match="logged in"):
        AgentCliProvider("claude-cli").analyse("p")


def test_empty_output_is_reported(monkeypatch):
    _patch(monkeypatch, FakeRun(stdout="   "))
    with pytest.raises(AgentCliError, match="no output"):
        AgentCliProvider("claude-cli").analyse("p")


def test_a_timeout_is_reported(monkeypatch):
    import subprocess

    monkeypatch.setattr("shutil.which", lambda n: "/usr/bin/claude")

    def timeout(*a, **k):
        raise subprocess.TimeoutExpired(cmd="claude", timeout=900)

    monkeypatch.setattr("subprocess.run", timeout)
    with pytest.raises(AgentCliError, match="did not finish"):
        AgentCliProvider("claude-cli").analyse("p")


def test_prose_around_the_json_is_tolerated(monkeypatch):
    _patch(monkeypatch, FakeRun(stdout=f"Here you go:\n```json\n{NOTE_JSON}\n```\n"))
    assert AgentCliProvider("claude-cli").analyse("p").title == "Standup"


def test_unusable_output_raises_a_parse_error(monkeypatch):
    _patch(monkeypatch, FakeRun(stdout="I could not do that"))
    with pytest.raises(ResponseParseError):
        AgentCliProvider("claude-cli").analyse("p")


def test_candidate_ids_are_enforced(monkeypatch):
    raw = NOTE_JSON[:-1] + ', "follow_up_of": "2020-01-01/Invented"}'
    _patch(monkeypatch, FakeRun(stdout=raw))
    note = AgentCliProvider("claude-cli").analyse("p", valid_candidate_ids=[])
    assert note.follow_up_of is None


def test_unknown_agent_raises():
    with pytest.raises(ValueError, match="unknown agent CLI"):
        AgentCliProvider("emacs-cli")


def test_every_agent_declares_a_binary():
    for provider in AGENT_COMMANDS:
        assert agent_binary(provider)
        assert isinstance(agent_available(provider), bool)


def test_the_factory_builds_a_cli_provider_without_a_key(monkeypatch):
    from beyondmeetings.config import Config
    from beyondmeetings.llm.factory import build_provider

    monkeypatch.setattr(
        "beyondmeetings.llm.factory.get_secret",
        lambda *a, **k: (_ for _ in ()).throw(AssertionError("must not need a key")),
    )
    provider = build_provider(Config(provider="claude-cli"))
    assert isinstance(provider, AgentCliProvider)


def test_claude_code_is_the_default_provider():
    from beyondmeetings.config import Config

    assert Config().provider == "claude-cli"
