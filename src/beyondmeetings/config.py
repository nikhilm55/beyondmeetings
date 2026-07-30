"""Non-secret configuration. Secrets live in the OS keyring — see secrets.py."""
from __future__ import annotations

import tomllib
from pathlib import Path

import tomli_w
from pydantic import BaseModel, Field

DEFAULT_CONFIG_PATH = Path.home() / ".config" / "beyondmeetings" / "config.toml"
DEFAULT_DATA_DIR = Path.home() / ".local" / "share" / "beyondmeetings"


class Config(BaseModel):
    vault_path: str = ""
    provider: str = "anthropic"
    model: str = ""
    transcriber: str = "groq"
    spoken_language: str = "auto"
    notes_language: str = "English"
    projects: list[str] = Field(default_factory=list)
    segment_minutes: int = 50
    data_dir: str = str(DEFAULT_DATA_DIR)
    ollama_host: str = "http://localhost:11434"
    ollama_num_ctx: int = 32768
    whisper_binary: str = ""
    whisper_model: str = "medium.en"


def load_config(path: Path | None = None) -> Config:
    path = path or DEFAULT_CONFIG_PATH
    if not path.exists():
        return Config()
    with path.open("rb") as fh:
        return Config(**tomllib.load(fh))


def save_config(config: Config, path: Path | None = None) -> None:
    path = path or DEFAULT_CONFIG_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("wb") as fh:
        tomli_w.dump(config.model_dump(), fh)
