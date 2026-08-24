"""Command-line entry point.

`start` never prompts for a name — a meeting is already under way, and every
second spent asking is audio lost. Unnamed recordings get a timestamp
placeholder and are retitled from the transcript at notes time.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from .audio.factory import build_recorder
from .config import DEFAULT_CONFIG_PATH, load_config
from .desktop import (
    DEFAULT_PORT, open_app, open_browser, open_browser_when_ready, wait_until,
)
from .doctor.base import completion_percent, run_all
from .doctor.registry import build_checks
from .llm.factory import MissingKeyError, build_provider
from .pipeline import generate_notes
from .session import SessionManager, placeholder_name  # noqa: F401 (re-exported)
from .transcribe.factory import build_transcriber


AUDIO_SUFFIXES = {".wav", ".mp3", ".m4a", ".ogg", ".opus", ".flac", ".webm"}

# uvicorn's own answer to a port it cannot have is `sys.exit(3)` — no exit
# code the user sees, and no hint about what to do next.
BIND_FAILURE = (
    "Could not start the server on port {port} — something else is already "
    "using it.\nIf that is beyondMeetings, open it with: beyondmeetings open"
)


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

    notes = sub.add_parser(
        "notes", help="write notes from a saved transcript or recording"
    )
    notes.add_argument("transcript", help="a .txt transcript or a .wav/.mp3 recording")

    sub.add_parser("doctor", help="check prerequisites")

    setup = sub.add_parser("setup", help="open the setup wizard")
    setup.add_argument("--port", type=int, default=DEFAULT_PORT)
    setup.add_argument("--no-browser", action="store_true")

    opener = sub.add_parser(
        "open", help="open the app, starting the server only if needed"
    )
    opener.add_argument("--port", type=int, default=DEFAULT_PORT)

    native = sub.add_parser("app", help="open the native desktop application")
    native.add_argument("--port", type=int, default=DEFAULT_PORT)
    native.add_argument("--setup", action="store_true", help="open Settings")

    serve = sub.add_parser("serve", help="run the app (page + tray)")
    serve.add_argument("--port", type=int, default=DEFAULT_PORT)
    serve.add_argument("--no-tray", action="store_true")
    serve.add_argument("--no-browser", action="store_true")

    return parser


def _provider(config):
    try:
        return build_provider(config)
    except (MissingKeyError, ValueError) as exc:
        raise SystemExit(str(exc)) from exc


def _session(config, data_dir: Path) -> SessionManager:
    """One stop pipeline, shared with the app.

    These were once two independent implementations and they diverged — only
    one compressed audio before upload, and only one used the segment cache.
    """
    return SessionManager(
        config=config,
        recorder=build_recorder(data_dir, segment_minutes=config.segment_minutes),
        transcriber_factory=build_transcriber,
        provider_factory=build_provider,
    )


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    config = load_config()
    data_dir = Path(config.data_dir)

    if args.command == "start":
        try:
            status = _session(config, data_dir).start(args.name or "")
        except RuntimeError as exc:
            raise SystemExit(str(exc)) from exc
        print(f"Recording started: {status['name']}")
        return 0

    if args.command == "stop":
        session = _session(config, data_dir)
        # Without this the terminal sits silent through compression, upload and
        # analysis. A user watching nothing happen assumes a hang and kills it,
        # which is exactly what happened on a 32-minute recording.
        session.on_phase_change = lambda phase: print(
            f"  {session.status()['detail'] or phase}…", flush=True
        )
        try:
            status = session.run_stop()
        except RuntimeError as exc:
            raise SystemExit(f"Nothing to stop — {exc}.") from exc

        if status["transcript_path"]:
            print(f"Transcript: {status['transcript_path']}")
        if status["phase"] == "failed":
            raise SystemExit(status["error"] or "Stop failed.")
        print(f"Note written: {status['note_path']}")
        return 0

    if args.command == "notes":
        source = Path(args.transcript).expanduser()
        if not source.is_file():
            raise SystemExit(f"No such file: {source}")

        if source.suffix.lower() in AUDIO_SUFFIXES:
            # Recovery path: an interrupted stop leaves audio with no
            # transcript, and previously nothing could pick it back up.
            from .segments import transcribe_segment

            try:
                transcriber = build_transcriber(config)
            except (RuntimeError, ValueError, FileNotFoundError) as exc:
                raise SystemExit(str(exc)) from exc
            print("  Transcribing (cached segments are reused)…", flush=True)
            transcript = transcribe_segment(source, transcriber)
        else:
            transcript = source.read_text(encoding="utf-8")

        print("  Writing notes…", flush=True)
        transcript_ref = None
        transcript_root = (Path(config.data_dir) / "transcripts").resolve()
        try:
            resolved_source = source.resolve()
            if resolved_source.is_relative_to(transcript_root):
                transcript_ref = str(resolved_source.relative_to(transcript_root))
        except (OSError, RuntimeError, ValueError):
            pass
        note_options = (
            {"transcript_ref": transcript_ref} if transcript_ref else {}
        )
        path = generate_notes(
            transcript,
            config,
            _provider(config),
            **note_options,
        )
        print(f"Note written: {path}")
        return 0

    if args.command == "doctor":
        rows = run_all(build_checks(config, config_path=DEFAULT_CONFIG_PATH))
        print(format_doctor_report(rows))
        return 0 if completion_percent(rows) == 100 else 1

    if args.command == "setup":
        import threading

        import uvicorn

        from .server import create_app

        url = f"http://127.0.0.1:{args.port}/setup"
        print(f"Setup wizard: {url}")
        server = uvicorn.Server(
            uvicorn.Config(
                create_app(config_path=DEFAULT_CONFIG_PATH),
                host="127.0.0.1",
                port=args.port,
                log_level="warning",
            )
        )
        stopped = threading.Event()
        if not args.no_browser:
            # Opened from a watcher thread — uvicorn has not bound the port yet.
            open_browser_when_ready(
                url, ready=lambda: server.started, cancelled=stopped.is_set
            )
        try:
            server.run()
        except SystemExit as exc:  # uvicorn exits the process on a bind failure
            if not exc.code:
                raise
            print(BIND_FAILURE.format(port=args.port), file=sys.stderr)
            return 1
        finally:
            stopped.set()
        return 0

    if args.command == "open":
        try:
            outcome = open_app(args.port)
        except RuntimeError as exc:
            raise SystemExit(str(exc)) from exc
        url = f"http://127.0.0.1:{args.port}/"
        print(
            f"beyondMeetings: {url}"
            + ("" if outcome == "started" else "  (already running)")
        )
        return 0

    if args.command == "app":
        from .desktop_app import run_native_app

        try:
            return run_native_app(
                port=args.port, page="/setup" if args.setup else "/"
            )
        except RuntimeError as exc:
            raise SystemExit(str(exc)) from exc

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

        # thread.start() returns long before uvicorn is accepting connections —
        # and, if the port is taken, before it has given up. uvicorn's
        # sys.exit() only kills this thread, so without the check `serve`
        # printed the URL, opened nothing and exited 0.
        wait_until(lambda: server.started or not thread.is_alive())
        if not server.started:
            print(BIND_FAILURE.format(port=args.port), file=sys.stderr)
            return 1

        print(f"beyondMeetings: {url}")
        if not args.no_browser:
            open_browser(url)

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
