"""The ordered list of prerequisite checks."""
from __future__ import annotations

from pathlib import Path

from ..config import DEFAULT_CONFIG_PATH, Config
from .autostart import AutostartCheck
from .base import Check
from .choices import ProviderChoice, TranscriberChoice
from .keys import GroqKeyCheck, ProviderKeyCheck
from .mcp import McpCheck
from .obsidian import ObsidianCheck
from .rules_check import RulesCheck
from .system import FfmpegCheck, PipeWireCheck
from .transcriber import WhisperModelCheck
from .vault import VaultCheck


def build_checks(
    config: Config,
    config_path: Path | None = None,
    secret_dir: Path | None = None,
) -> list[Check]:
    config_path = Path(config_path or DEFAULT_CONFIG_PATH)
    checks: list[Check] = [
        # Choices first — they change what the rows below mean.
        ProviderChoice(config, config_path=config_path),
        TranscriberChoice(config, config_path=config_path),
        PipeWireCheck(),
        FfmpegCheck(),
    ]

    # The Groq key is only a prerequisite when Groq is doing the transcribing.
    if config.transcriber == "groq":
        checks.append(GroqKeyCheck(secret_dir=secret_dir))

    checks += [
        ProviderKeyCheck(
            provider=config.provider,
            secret_dir=secret_dir,
            ollama_host=config.ollama_host,
            model=config.model,
            agent_command=config.agent_command or None,
        ),
        WhisperModelCheck(config),
        ObsidianCheck(),
        VaultCheck(config, config_path=config_path),
        RulesCheck(config),
        McpCheck(config),
        AutostartCheck(config),
    ]
    return checks
