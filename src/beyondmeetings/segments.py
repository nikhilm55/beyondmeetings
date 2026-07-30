"""Per-segment transcript caching.

A segment is transcribed as soon as it closes, while the next one records, and
the result is cached beside its audio. By the time the user stops, only the
final segment is usually left. This is what spreads Groq calls across the real
duration of a meeting instead of bursting them at the end.
"""
from __future__ import annotations

from pathlib import Path
from typing import Callable, Iterable

from .transcribe.base import Transcriber


def transcript_path(audio: Path) -> Path:
    return Path(audio).with_suffix(".txt")


def cached_transcript(audio: Path) -> str | None:
    path = transcript_path(audio)
    if path.is_file():
        return path.read_text(encoding="utf-8", errors="replace")
    return None


def transcribe_segment(audio: Path, transcriber: Transcriber) -> str:
    """Transcribe one segment and cache the result. Returns the cache if present."""
    existing = cached_transcript(audio)
    if existing is not None:
        return existing

    audio = Path(audio)
    if not audio.is_file():
        raise FileNotFoundError(
            f"{audio} is gone and has no cached transcript beside it."
        )

    text = transcriber.transcribe_file(audio).strip()
    transcript_path(audio).write_text(text, encoding="utf-8")
    return text


def combine_transcripts(
    segments: Iterable[Path],
    transcriber: Transcriber,
    on_progress: Callable[[int, int], None] | None = None,
) -> str:
    segments = [Path(s) for s in segments]
    parts: list[str] = []
    for index, audio in enumerate(segments, start=1):
        parts.append(transcribe_segment(audio, transcriber))
        if on_progress:
            on_progress(index, len(segments))
    return "\n".join(parts)


def discard_audio(audio: Path) -> None:
    """Drop a segment's audio once its transcript is safely on disk."""
    Path(audio).unlink(missing_ok=True)
