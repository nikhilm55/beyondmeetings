"""Command-line entry point.

`start` never prompts for a name — a meeting is already under way, and every
second spent asking is audio lost. Unnamed recordings get a timestamp
placeholder and are retitled from the transcript at notes time.
"""
from __future__ import annotations

import argparse
import sys
from datetime import datetime
from pathlib import Path

from .audio.pipewire import PipeWireRecorder
from .config import load_config
from .llm.anthropic import AnthropicProvider
from .pipeline import generate_notes
from .secrets import get_secret
from .transcribe.groq import GroqTranscriber, compress_for_upload


def placeholder_name() -> str:
    return datetime.now().strftime("recording-%H-%M")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="beyondmeetings")
    sub = parser.add_subparsers(dest="command", required=True)

    start = sub.add_parser("start", help="start recording")
    start.add_argument("name", nargs="?", default=None)

    sub.add_parser("stop", help="stop, transcribe and write notes")

    notes = sub.add_parser("notes", help="regenerate notes from a transcript")
    notes.add_argument("transcript")

    return parser


def _provider(config):
    key = get_secret("anthropic_api_key")
    if not key:
        raise SystemExit("No Anthropic API key stored. Run `beyondmeetings setup`.")
    return AnthropicProvider(api_key=key, model=config.model)


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    config = load_config()
    data_dir = Path(config.data_dir)

    if args.command == "start":
        name = args.name or placeholder_name()
        recorder = PipeWireRecorder(data_dir, segment_minutes=config.segment_minutes)
        state = recorder.start(name)
        print(f"Recording started: {state.name}")
        return 0

    if args.command == "stop":
        recorder = PipeWireRecorder(data_dir, segment_minutes=config.segment_minutes)
        state = recorder.stop()

        key = get_secret("groq_api_key")
        if not key:
            raise SystemExit("No Groq API key stored. Run `beyondmeetings setup`.")
        transcriber = GroqTranscriber(api_key=key, language=config.spoken_language)

        parts = []
        for segment in state.segments:
            source = Path(segment)
            if not source.exists():
                continue
            mp3 = source.with_suffix(".mp3")
            compress_for_upload(source, mp3)
            parts.append(transcriber.transcribe_file(mp3))

        transcript = "\n".join(parts)
        folder = data_dir / "transcripts" / state.date
        folder.mkdir(parents=True, exist_ok=True)
        transcript_path = folder / f"{state.filename_base}.txt"
        transcript_path.write_text(transcript, encoding="utf-8")
        print(f"Transcript: {transcript_path}")

        path = generate_notes(transcript, config, _provider(config), state.date)
        print(f"Note written: {path}")
        return 0

    if args.command == "notes":
        transcript = Path(args.transcript).read_text(encoding="utf-8")
        path = generate_notes(transcript, config, _provider(config))
        print(f"Note written: {path}")
        return 0

    return 1


if __name__ == "__main__":
    sys.exit(main())
