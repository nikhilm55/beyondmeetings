"""Command-line entry point.

`start` never prompts for a name — a meeting is already under way, and every
second spent asking is audio lost. Unnamed recordings get a timestamp
placeholder and are retitled from the transcript at notes time.
"""
from __future__ import annotations

import argparse
import sys
import webbrowser
from datetime import datetime
from pathlib import Path

from .audio.pipewire import PipeWireRecorder
from .config import DEFAULT_CONFIG_PATH, load_config
from .doctor.base import completion_percent, run_all
from .doctor.registry import build_checks
from .llm.factory import MissingKeyError, build_provider
from .pipeline import generate_notes
from .transcribe.factory import build_transcriber
from .transcribe.groq import compress_for_upload


def placeholder_name() -> str:
    return datetime.now().strftime("recording-%H-%M")


def format_doctor_report(rows: list[dict]) -> str:
    lines = [f"beyondMeetings — {completion_percent(rows)}% ready", ""]
    for row in rows:
        mark = "✓" if row["status"] == "ok" else "✗"
        suffix = "" if row["required"] else "  (optional)"
        lines.append(f"  {mark} {row['label']}{suffix}")
        if row["detail"]:
            lines.append(f"      {row['detail']}")
    return "\n".join(lines)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="beyondmeetings")
    sub = parser.add_subparsers(dest="command", required=True)

    start = sub.add_parser("start", help="start recording")
    start.add_argument("name", nargs="?", default=None)

    sub.add_parser("stop", help="stop, transcribe and write notes")

    notes = sub.add_parser("notes", help="regenerate notes from a transcript")
    notes.add_argument("transcript")

    sub.add_parser("doctor", help="check prerequisites")

    setup = sub.add_parser("setup", help="open the setup wizard")
    setup.add_argument("--port", type=int, default=7788)
    setup.add_argument("--no-browser", action="store_true")

    serve = sub.add_parser("serve", help="run the app (page + tray)")
    serve.add_argument("--port", type=int, default=7788)
    serve.add_argument("--no-tray", action="store_true")
    serve.add_argument("--no-browser", action="store_true")

    return parser


def _provider(config):
    try:
        return build_provider(config)
    except (MissingKeyError, ValueError) as exc:
        raise SystemExit(str(exc)) from exc


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
        try:
            state = recorder.stop()
        except RuntimeError as exc:
            raise SystemExit(f"Nothing to stop — {exc}.") from exc

        try:
            transcriber = build_transcriber(config)
        except (RuntimeError, ValueError, FileNotFoundError) as exc:
            raise SystemExit(str(exc)) from exc

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

    if args.command == "doctor":
        rows = run_all(build_checks(config, config_path=DEFAULT_CONFIG_PATH))
        print(format_doctor_report(rows))
        return 0 if completion_percent(rows) == 100 else 1

    if args.command == "setup":
        import uvicorn

        from .server import create_app

        url = f"http://127.0.0.1:{args.port}/setup"
        print(f"Setup wizard: {url}")
        if not args.no_browser:
            webbrowser.open(url)
        uvicorn.run(
            create_app(config_path=DEFAULT_CONFIG_PATH),
            host="127.0.0.1",
            port=args.port,
            log_level="warning",
        )
        return 0

    if args.command == "serve":
        import threading

        import uvicorn

        from .server import create_app
        from .tray import TRAY_HINT, run_tray, tray_available

        url = f"http://127.0.0.1:{args.port}/"
        application = create_app(config_path=DEFAULT_CONFIG_PATH)
        server = uvicorn.Server(
            uvicorn.Config(
                application, host="127.0.0.1", port=args.port, log_level="warning"
            )
        )
        thread = threading.Thread(target=server.run, daemon=True)
        thread.start()
        print(f"beyondMeetings: {url}")

        if not args.no_browser:
            webbrowser.open(url)

        if args.no_tray or not tray_available():
            if not args.no_tray:
                print(TRAY_HINT)
            try:
                thread.join()
            except KeyboardInterrupt:
                print()
            return 0

        # The tray drives the same session the page does.
        run_tray(url, session=application.state.session_getter())
        return 0

    return 1


if __name__ == "__main__":
    sys.exit(main())
