"""Whisper model presence — only relevant for local transcription."""
from __future__ import annotations

from ..config import Config
from ..transcribe.whispercpp import default_model_path
from .base import Check, CheckResult


class WhisperModelCheck(Check):
    id = "whisper_model"
    label = "Local speech model"
    description = "The whisper.cpp model file used for offline transcription."
    required = False

    def __init__(self, config: Config):
        self.config = config

    def detect(self) -> CheckResult:
        if self.config.transcriber != "whispercpp":
            return CheckResult(status="ok", detail="Not needed — using Groq.")

        path = default_model_path(self.config.whisper_model)
        if path.is_file() and path.stat().st_size > 0:
            return CheckResult(status="ok", detail=str(path))
        return CheckResult(
            status="missing",
            detail=f"Model {self.config.whisper_model} not downloaded (~1.5 GB).",
        )

    @property
    def fixable(self) -> bool:
        return self.config.transcriber == "whispercpp"

    def fix(self, **kwargs) -> CheckResult:
        from ..transcribe.whispercpp import download_model

        download_model(self.config.whisper_model)
        return self.detect()
