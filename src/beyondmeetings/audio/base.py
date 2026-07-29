"""Recorder interface and recording state.

One JSON file replaces the six dotfiles the shell pipeline scattered through
the home directory (.record_pid, .current_recording, .current_name,
.current_filename, .mix_modules, .current_followup).

macOS/Windows support means adding a sibling of pipewire.py implementing
Recorder — nothing else changes.
"""
from __future__ import annotations

import json
from abc import ABC, abstractmethod
from pathlib import Path

from pydantic import BaseModel, Field


class RecordingState(BaseModel):
    name: str
    filename_base: str
    date: str
    pid: int
    module_ids: list[int] = Field(default_factory=list)
    segments: list[str] = Field(default_factory=list)
    started_at: str


def save_state(state: RecordingState, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(state.model_dump_json(indent=2))


def load_state(path: Path) -> RecordingState | None:
    if not path.exists():
        return None
    try:
        return RecordingState(**json.loads(path.read_text()))
    except (json.JSONDecodeError, TypeError, ValueError) as exc:
        raise ValueError(f"corrupt recording state at {path}: {exc}") from exc


def clear_state(path: Path) -> None:
    path.unlink(missing_ok=True)


class Recorder(ABC):
    @abstractmethod
    def start(self, name: str) -> RecordingState:
        ...

    @abstractmethod
    def stop(self) -> RecordingState:
        ...

    @abstractmethod
    def status(self) -> RecordingState | None:
        ...
