"""Non-secret configuration. Secrets live in the OS keyring — see secrets.py."""
from __future__ import annotations

from pathlib import Path

from platformdirs import user_config_path, user_data_path

try:
    import tomllib  # Python 3.11+
except ModuleNotFoundError:  # pragma: no cover - depends on interpreter
    import tomli as tomllib

import tomli_w
from pydantic import BaseModel, Field

DEFAULT_CONFIG_PATH = user_config_path("beyondmeetings", appauthor=False) / "config.toml"
DEFAULT_DATA_DIR = user_data_path("beyondmeetings", appauthor=False)
DEFAULT_LIBRARY_DIR = DEFAULT_DATA_DIR / "library"


class Config(BaseModel):
    # `library_path` is the app-owned Markdown library. `vault_path` remains
    # readable for a seamless upgrade from releases which required Obsidian.
    library_path: str = ""
    vault_path: str = Field(default="", exclude=True)
    provider: str = "claude-cli"
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
    # Override the agent CLI invocation without a code change.
    agent_command: list[str] = Field(default_factory=list)

    @property
    def notes_path(self) -> str:
        """Effective note library, including migration from old configs."""
        return self.library_path or self.vault_path or str(DEFAULT_LIBRARY_DIR)


def load_config(path: Path | None = None) -> Config:
    path = path or DEFAULT_CONFIG_PATH
    if not path.exists():
        return Config()
    with path.open("rb") as fh:
        data = tomllib.load(fh)
    if data.get("vault_path") and not data.get("library_path"):
        data["library_path"] = data.pop("vault_path")
    return Config(**data)


def save_config(config: Config, path: Path | None = None) -> None:
    path = path or DEFAULT_CONFIG_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    data = config.model_dump()
    # Reading an old `vault_path` is supported, but the next save migrates it
    # permanently to the app-owned library setting.
    data["library_path"] = config.notes_path
    with path.open("wb") as fh:
        tomli_w.dump(data, fh)
