"""Groq Whisper adapter.

Fixes two bugs from the original shell pipeline: ffmpeg is resolved from PATH
rather than a hardcoded personal node_modules path, and the language is
configurable — forcing "en" made Whisper translate code-mixed speech instead
of transcribing it.
"""
from __future__ import annotations

import re
import shutil
import subprocess
import tempfile
import time
from pathlib import Path

import httpx

from .base import Transcriber

API_URL = "https://api.groq.com/openai/v1/audio/transcriptions"
MODELS = ("whisper-large-v3", "whisper-large-v3-turbo")
TIMEOUT = 600.0
DEFAULT_RETRY_WAIT = 30.0

# Formats that are already small enough to upload as-is.
COMPRESSED_SUFFIXES = {".mp3", ".m4a", ".ogg", ".opus", ".flac", ".webm"}

_LEADING_NUMBER = re.compile(r"^\s*([\d.]+)")


def parse_retry_after(value: str | None) -> float:
    """Seconds to wait. Groq sends forms like '7.66s'; RFC 9110 also permits
    an HTTP-date. Anything unparseable falls back rather than crashing a
    transcription that is otherwise fine."""
    if not value:
        return DEFAULT_RETRY_WAIT
    match = _LEADING_NUMBER.match(value)
    if not match:
        return DEFAULT_RETRY_WAIT
    try:
        return float(match.group(1))
    except ValueError:
        return DEFAULT_RETRY_WAIT


def resolve_ffmpeg() -> str:
    found = shutil.which("ffmpeg")
    if not found:
        raise FileNotFoundError(
            "ffmpeg not found on PATH. Install it with your package manager "
            "(apt install ffmpeg / dnf install ffmpeg / pacman -S ffmpeg)."
        )
    return found


def compress_for_upload(source: Path, dest: Path) -> Path:
    """Mono 16 kHz 32 kbps MP3 — small enough to upload, ample for speech."""
    subprocess.run(
        [resolve_ffmpeg(), "-i", str(source), "-ac", "1", "-ar", "16000",
         "-b:a", "32k", str(dest), "-y", "-loglevel", "error"],
        check=True,
    )
    return dest


class GroqTranscriber(Transcriber):
    def __init__(
        self,
        api_key: str,
        language: str = "auto",
        max_attempts: int = 3,
        backoff_base: float = 3.0,
    ):
        self.api_key = api_key
        self.language = language
        self.max_attempts = max_attempts
        self.backoff_base = backoff_base

    def _post(self, audio: Path, model: str) -> httpx.Response:
        data = {"model": model, "response_format": "text"}
        if self.language and self.language != "auto":
            data["language"] = self.language
        with audio.open("rb") as fh:
            return httpx.post(
                API_URL,
                timeout=TIMEOUT,
                headers={"Authorization": f"Bearer {self.api_key}"},
                files={"file": (audio.name, fh, "audio/mpeg")},
                data=data,
            )

    def transcribe_file(self, audio: Path) -> str:
        """Compression happens here, not in the caller.

        Raw PipeWire capture is ~384 kB/s, so a 50-minute segment is over a
        gigabyte against Groq's 25 MB limit. Two separate stop pipelines once
        existed and only one of them remembered to compress; putting it behind
        this method makes forgetting impossible.
        """
        audio = Path(audio)
        if audio.suffix.lower() in COMPRESSED_SUFFIXES:
            return self._transcribe_prepared(audio)

        with tempfile.TemporaryDirectory(prefix="beyondmeetings-") as tmp:
            small = compress_for_upload(audio, Path(tmp) / f"{audio.stem}.mp3")
            return self._transcribe_prepared(small)

    def _transcribe_prepared(self, audio: Path) -> str:
        last = ""
        for model in MODELS:
            for attempt in range(1, self.max_attempts + 1):
                response = self._post(audio, model)
                if response.status_code == 200:
                    return response.text.strip()

                last = f"HTTP {response.status_code}: {response.text[:200]}"
                if response.status_code == 429:
                    time.sleep(parse_retry_after(response.headers.get("retry-after")))
                    continue
                time.sleep(self.backoff_base * attempt)

        raise RuntimeError(f"Groq transcription failed after all retries — {last}")
