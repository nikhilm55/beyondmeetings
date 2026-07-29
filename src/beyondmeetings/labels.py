"""Human-readable names for the identifiers stored in config.

Config stores machine ids ("groq", "anthropic"); notes are read by people.
"""
from __future__ import annotations

TRANSCRIBERS = {
    "groq": "Groq Whisper",
    "whispercpp": "whisper.cpp",
}

PROVIDERS = {
    "anthropic": "Claude",
    "openai": "ChatGPT",
    "gemini": "Gemini",
    "ollama": "Ollama",
}


def transcriber_label(key: str) -> str:
    return TRANSCRIBERS.get(key, key)


def provider_label(key: str) -> str:
    return PROVIDERS.get(key, key)
