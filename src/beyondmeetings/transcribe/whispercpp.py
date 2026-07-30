"""Local transcription via whisper.cpp.

Nothing leaves the machine. The binary has to be built by the user — that
needs a compiler and is not something an installer should attempt silently —
but the model file can be downloaded automatically.
"""
from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Callable

import httpx

from .base import Transcriber

MODEL_URL = (
    "https://huggingface.co/ggerganov/whisper.cpp/resolve/main/ggml-{model}.bin"
)
DEFAULT_MODEL_NAME = "medium.en"

# whisper.cpp is usually built from source rather than packaged, so PATH is
# frequently not where it lives.
KNOWN_LOCATIONS = (
    "whispercpp/whisper.cpp/build/bin/whisper-cli",
    "whisper.cpp/build/bin/whisper-cli",
    ".local/share/beyondmeetings/whisper.cpp/build/bin/whisper-cli",
)

BUILD_HINT = (
    "whisper.cpp not found. Build it:\n"
    "  git clone https://github.com/ggerganov/whisper.cpp\n"
    "  cd whisper.cpp && cmake -B build && cmake --build build -j\n"
    "Then set whisper_binary in ~/.config/beyondmeetings/config.toml."
)


def resolve_whisper_binary(configured: str = "") -> str:
    if configured:
        candidate = Path(configured).expanduser()
        if candidate.is_file() and os.access(candidate, os.X_OK):
            return str(candidate)

    found = shutil.which("whisper-cli")
    if found:
        return found

    for relative in KNOWN_LOCATIONS:
        candidate = Path.home() / relative
        if candidate.is_file() and os.access(candidate, os.X_OK):
            return str(candidate)

    raise FileNotFoundError(BUILD_HINT)


def default_model_path(model: str = DEFAULT_MODEL_NAME) -> Path:
    return (
        Path.home() / ".local" / "share" / "beyondmeetings" / "models"
        / f"ggml-{model}.bin"
    )


def download_model(
    model: str = DEFAULT_MODEL_NAME,
    dest: Path | None = None,
    on_progress: Callable[[int, int], None] | None = None,
) -> Path:
    """Fetch a ggml model. ~1.5 GB for medium.en, so progress is reported."""
    dest = Path(dest or default_model_path(model))
    dest.parent.mkdir(parents=True, exist_ok=True)
    if dest.is_file() and dest.stat().st_size > 0:
        return dest

    partial = dest.with_suffix(".partial")
    with httpx.stream(
        "GET", MODEL_URL.format(model=model), follow_redirects=True, timeout=None
    ) as response:
        response.raise_for_status()
        total = int(response.headers.get("content-length", 0))
        done = 0
        with partial.open("wb") as fh:
            for chunk in response.iter_bytes(1 << 20):
                fh.write(chunk)
                done += len(chunk)
                if on_progress:
                    on_progress(done, total)
    partial.replace(dest)
    return dest


def _run(args: list[str]) -> int:
    return subprocess.run(args, capture_output=True, text=True).returncode


class WhisperCppTranscriber(Transcriber):
    def __init__(
        self,
        binary: str = "",
        model_path: str = "",
        language: str = "auto",
        threads: int = 0,
        runner: Callable[[list[str]], int] | None = None,
    ):
        self.binary = binary or resolve_whisper_binary()
        self.model_path = model_path or str(default_model_path())
        self.language = language
        self.threads = threads or (os.cpu_count() or 4)
        self.runner = runner or _run

    def transcribe_file(self, audio: Path) -> str:
        with tempfile.TemporaryDirectory() as tmp:
            stem = str(Path(tmp) / "out")
            args = [
                self.binary,
                "--model", self.model_path,
                "--file", str(audio),
                "--output-txt",
                "--output-file", stem,
                "--threads", str(self.threads),
                "--no-prints",
            ]
            if self.language and self.language != "auto":
                args += ["--language", self.language]

            if self.runner(args) != 0:
                raise RuntimeError(
                    f"whisper.cpp failed on {audio.name}. "
                    f"Check the model at {self.model_path}."
                )

            produced = Path(f"{stem}.txt")
            if not produced.is_file():
                raise RuntimeError(
                    f"whisper.cpp produced no transcript for {audio.name}."
                )
            return produced.read_text(encoding="utf-8", errors="replace").strip()
