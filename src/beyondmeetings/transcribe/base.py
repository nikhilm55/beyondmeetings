from __future__ import annotations

from abc import ABC, abstractmethod
from pathlib import Path


class Transcriber(ABC):
    @abstractmethod
    def transcribe_file(self, audio: Path) -> str:
        """Return the transcript text for a single audio file."""
