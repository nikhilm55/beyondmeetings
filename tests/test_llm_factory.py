import pytest

from beyondmeetings.config import Config
from beyondmeetings.llm.anthropic import AnthropicProvider
from beyondmeetings.llm.factory import MissingKeyError, build_provider
from beyondmeetings.llm.gemini import GeminiProvider
from beyondmeetings.llm.ollama import OllamaProvider
from beyondmeetings.llm.openai import OpenAIProvider


def test_builds_the_agent_cli_by_default(monkeypatch):
    """The default must not require an API key — most users have none."""
    from beyondmeetings.llm.agent_cli import AgentCliProvider

    monkeypatch.setattr("beyondmeetings.llm.factory.get_secret", lambda *a, **k: "sk-x")
    assert isinstance(build_provider(Config()), AgentCliProvider)


def test_builds_anthropic_when_explicitly_chosen(monkeypatch):
    monkeypatch.setattr("beyondmeetings.llm.factory.get_secret", lambda *a, **k: "sk-x")
    assert isinstance(build_provider(Config(provider="anthropic")), AnthropicProvider)


def test_builds_each_supported_provider(monkeypatch):
    monkeypatch.setattr("beyondmeetings.llm.factory.get_secret", lambda *a, **k: "key")
    expected = {
        "anthropic": AnthropicProvider,
        "openai": OpenAIProvider,
        "gemini": GeminiProvider,
    }
    for name, cls in expected.items():
        assert isinstance(build_provider(Config(provider=name)), cls)


def test_ollama_needs_no_key(monkeypatch):
    monkeypatch.setattr("beyondmeetings.llm.factory.get_secret", lambda *a, **k: None)
    assert isinstance(build_provider(Config(provider="ollama")), OllamaProvider)


def test_ollama_host_is_passed_through(monkeypatch):
    monkeypatch.setattr("beyondmeetings.llm.factory.get_secret", lambda *a, **k: None)
    provider = build_provider(Config(provider="ollama", ollama_host="http://box:9"))
    assert provider.host == "http://box:9"


def test_missing_key_raises_with_actionable_message(monkeypatch):
    monkeypatch.setattr("beyondmeetings.llm.factory.get_secret", lambda *a, **k: None)
    with pytest.raises(MissingKeyError, match="beyondmeetings setup"):
        build_provider(Config(provider="anthropic"))


def test_unknown_provider_raises(monkeypatch):
    monkeypatch.setattr("beyondmeetings.llm.factory.get_secret", lambda *a, **k: "k")
    with pytest.raises(ValueError, match="unknown provider"):
        build_provider(Config(provider="nope"))


def test_configured_model_overrides_the_default(monkeypatch):
    monkeypatch.setattr("beyondmeetings.llm.factory.get_secret", lambda *a, **k: "k")
    provider = build_provider(Config(provider="anthropic", model="claude-sonnet-5"))
    assert provider.model == "claude-sonnet-5"


def test_each_provider_reads_its_own_secret_name(monkeypatch):
    asked = []
    monkeypatch.setattr(
        "beyondmeetings.llm.factory.get_secret",
        lambda name, **k: asked.append(name) or "k",
    )
    build_provider(Config(provider="gemini"))
    assert asked == ["gemini_api_key"]
