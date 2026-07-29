"""The ordered list of prerequisite checks."""
from __future__ import annotations

from pathlib import Path

from ..config import DEFAULT_CONFIG_PATH, Config
from .base import Check
from .keys import GroqKeyCheck, ProviderKeyCheck
from .obsidian import ObsidianCheck
from .rules_check import RulesCheck
from .system import FfmpegCheck, PipeWireCheck
from .vault import VaultCheck


def build_checks(
    config: Config,
    config_path: Path | None = None,
    secret_dir: Path | None = None,
) -> list[Check]:
    config_path = Path(config_path or DEFAULT_CONFIG_PATH)
    rules_dir = Path(config.vault_path) if config.vault_path else config_path.parent
    return [
        PipeWireCheck(),
        FfmpegCheck(),
        GroqKeyCheck(secret_dir=secret_dir),
        ProviderKeyCheck(provider=config.provider, secret_dir=secret_dir),
        ObsidianCheck(),
        VaultCheck(config, config_path=config_path),
        RulesCheck(config, target_dir=rules_dir),
    ]
