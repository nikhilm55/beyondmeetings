"""Build the configured transcriber."""
from __future__ import annotations

from ..config import Config
from ..secrets import get_secret
from .base import Transcriber
from .groq import GroqTranscriber
from .whispercpp import WhisperCppTranscriber, default_model_path


def build_transcriber(config: Config) -> Transcriber:
    if config.transcriber == "groq":
        key = get_secret("groq_api_key")
        if not key:
            raise RuntimeError(
                "No Groq API key stored. Run `beyondmeetings setup` to add one, "
                "or switch to local transcription."
            )
        return GroqTranscriber(api_key=key, language=config.spoken_language)

    if config.transcriber == "whispercpp":
        return WhisperCppTranscriber(
            binary=config.whisper_binary,
            model_path=str(default_model_path(config.whisper_model)),
            language=config.spoken_language,
        )

    raise ValueError(f"unknown transcriber: {config.transcriber}")
