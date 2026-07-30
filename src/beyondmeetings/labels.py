"""Human-readable names for the identifiers stored in config.

Config stores machine ids ("groq", "anthropic"); notes are read by people.
"""
from __future__ import annotations

TRANSCRIBERS = {
    "groq": "Groq Whisper",
    "whispercpp": "whisper.cpp",
}

PROVIDERS = {
    # No API key — these drive an already-installed CLI on the user's
    # existing subscription.
    "claude-cli": "Claude Code",
    "gemini-cli": "Gemini CLI",
    "codex-cli": "Codex CLI",
    # API key required.
    "anthropic": "Claude API",
    "openai": "ChatGPT API",
    "gemini": "Gemini API",
    "ollama": "Ollama",
}


def transcriber_label(key: str) -> str:
    return TRANSCRIBERS.get(key, key)


def provider_label(key: str) -> str:
    return PROVIDERS.get(key, key)
