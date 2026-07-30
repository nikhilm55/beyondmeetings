"""Build the configured note-writing provider."""
from __future__ import annotations

from ..config import Config
from ..labels import provider_label
from ..secrets import get_secret
from .anthropic import AnthropicProvider
from .base import LLMProvider
from .gemini import GeminiProvider
from .ollama import OllamaProvider
from .openai import OpenAIProvider


class MissingKeyError(RuntimeError):
    """No API key stored for the configured provider."""


# Ollama runs locally and needs no key.
KEYED = {
    "anthropic": AnthropicProvider,
    "openai": OpenAIProvider,
    "gemini": GeminiProvider,
}


def build_provider(config: Config) -> LLMProvider:
    name = config.provider

    if name == "ollama":
        return OllamaProvider(
            model=config.model,
            host=config.ollama_host,
            num_ctx=config.ollama_num_ctx,
        )

    cls = KEYED.get(name)
    if cls is None:
        raise ValueError(f"unknown provider: {name}")

    key = get_secret(f"{name}_api_key")
    if not key:
        raise MissingKeyError(
            f"No {provider_label(name)} API key stored. "
            "Run `beyondmeetings setup` to add one."
        )
    return cls(api_key=key, model=config.model)
