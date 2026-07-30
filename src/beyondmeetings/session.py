"""Recording session lifecycle and the stop pipeline.

Stopping takes minutes, so `stop()` spawns a thread and the page polls
`status()`. `run_stop()` is the synchronous body — tests call it directly and
never touch threads.

The transcript is written to disk *before* the LLM is called. Losing an hour of
audio because note generation failed would be unacceptable; a saved transcript
can always be re-run.
"""
from __future__ import annotations

import logging
import threading
from datetime import datetime
from pathlib import Path
from typing import Callable

from .config import Config
from .pipeline import generate_notes
from .rollover import RolloverWorker
from .segments import combine_transcripts, discard_audio, transcribe_segment

log = logging.getLogger(__name__)

TICK_SECONDS = 20
# Long enough for an in-flight roll_segment (kill + respawn pw-record) to land.
TICKER_JOIN_TIMEOUT = 30
BUSY_PHASES = ("stopping", "transcribing", "analysing")


def placeholder_name(now: datetime | None = None) -> str:
    """Name for an unnamed recording. Defined once — the CLI imports it."""
    return (now or datetime.now()).strftime("recording-%H-%M")


class SessionManager:
    def __init__(
        self,
        config: Config,
        recorder,
        transcriber_factory: Callable[[Config], object],
        provider_factory: Callable[[Config], object],
        clock: Callable[[], datetime] = datetime.now,
    ):
        self.config = config
        self.recorder = recorder
        self.transcriber_factory = transcriber_factory
        self.provider_factory = provider_factory
        self.clock = clock
        self.on_phase_change: Callable[[str], None] | None = None

        self._lock = threading.Lock()
        self._phase = "idle"
        self._detail = ""
        self._error: str | None = None
        self._note_path: str | None = None
        self._transcript_path: str | None = None
        self._segments_done = 0
        self._segments_total = 0
        self._started_at: datetime | None = None
        self._name = ""
        self._rollover_error: str | None = None
        self._stop_thread: threading.Thread | None = None
        self._ticker: threading.Thread | None = None
        self._ticker_stop = threading.Event()

        self._rollover = RolloverWorker(
            recorder=recorder,
            segment_minutes=config.segment_minutes,
            on_segment_closed=self._segment_closed,
        )

    # ---------- state ----------

    def _set_phase(self, phase: str, detail: str = "") -> None:
        with self._lock:
            self._phase = phase
            self._detail = detail
        if self.on_phase_change:
            self.on_phase_change(phase)

    def status(self) -> dict:
        with self._lock:
            recording = self.recorder.status() is not None
            elapsed = 0
            if recording and self._started_at:
                elapsed = int((self.clock() - self._started_at).total_seconds())
            return {
                "phase": self._phase,
                "detail": self._detail,
                "recording": recording,
                "name": self._name,
                "elapsed_seconds": elapsed,
                "segments_done": self._segments_done,
                "segments_total": self._segments_total,
                "note_path": self._note_path,
                "transcript_path": self._transcript_path,
                "error": self._error,
                # A dead ticker or an unreadable state file used to be visible
                # only in the log — the user found out at stop time.
                "rollover_error": self._rollover_error,
                "state_error": getattr(self.recorder, "state_error", None),
            }

    # ---------- start ----------

    def start(self, name: str = "") -> dict:
        """Guards, state mutation and recorder.start() are all one atomic step.

        FastAPI dispatches sync endpoints to a threadpool, so two tabs or a
        double-click really can arrive concurrently. Check-then-act outside the
        lock let every caller through, each loading its own PipeWire modules
        that nothing could later tear down.
        """
        with self._lock:
            if self.recorder.status() is not None:
                raise RuntimeError("already recording")
            if self._phase in BUSY_PHASES:
                raise RuntimeError(f"still {self._phase} the previous meeting")

            name = (name or "").strip() or placeholder_name(self.clock())
            self._error = None
            self._note_path = None
            self._transcript_path = None
            self._segments_done = 0
            self._segments_total = 0
            self._name = name
            self._started_at = self.clock()
            self._rollover_error = None

            self.recorder.start(name)
            self._rollover.mark_segment_start(self._started_at)

        self._set_phase("recording")
        self._start_ticker()
        return self.status()

    def reset(self) -> dict:
        """Recover from a wedged or corrupt recording state."""
        with self._lock:
            self._ticker_stop.set()
            if hasattr(self.recorder, "reset"):
                self.recorder.reset()
            self._error = None
            self._rollover_error = None
        self._set_phase("idle", "Recording state cleared.")
        return self.status()

    def _start_ticker(self) -> None:
        self._ticker_stop.clear()

        def loop():
            while not self._ticker_stop.wait(TICK_SECONDS):
                try:
                    self._rollover.tick(self.clock())
                    with self._lock:
                        self._rollover_error = None
                except Exception as exc:
                    log.exception("rollover tick failed")
                    # Segmentation is now dead for the rest of the meeting.
                    # Say so, rather than discovering it as a 429 at stop time.
                    with self._lock:
                        self._rollover_error = (
                            f"Segmentation stopped: {exc}. A long meeting may hit "
                            "transcription rate limits at stop time."
                        )

        self._ticker = threading.Thread(target=loop, daemon=True)
        self._ticker.start()

    def _segment_closed(self, audio: str) -> None:
        """Transcribe a closed segment while the next one records."""
        transcriber = self.transcriber_factory(self.config)
        transcribe_segment(Path(audio), transcriber)
        # Earlier segments' audio is no longer needed once cached — a
        # multi-hour meeting would otherwise accumulate gigabytes.
        discard_audio(Path(audio))

    # ---------- stop ----------

    def stop(self) -> dict:
        if self.recorder.status() is None:
            raise RuntimeError("no active recording")
        self._stop_thread = threading.Thread(target=self.run_stop, daemon=True)
        self._stop_thread.start()
        return self.status()

    def run_stop(self) -> dict:
        if self.recorder.status() is None:
            raise RuntimeError("no active recording")

        # Event.set() does not wait. A mid-flight roll_segment() would finish
        # after teardown, re-create the state file the stop just deleted, and
        # leave the app permanently unable to start or stop.
        self._ticker_stop.set()
        ticker = self._ticker
        if ticker is not None and ticker.is_alive():
            ticker.join(timeout=TICKER_JOIN_TIMEOUT)

        self._set_phase("stopping")
        state = self.recorder.stop()

        try:
            transcript = self._transcribe(state)
            self._write_transcript(state, transcript)
        except Exception as exc:
            log.exception("transcription failed")
            self._fail(f"Transcription failed: {exc}")
            return self.status()

        try:
            self._set_phase("analysing", "Writing notes")
            provider = self.provider_factory(self.config)
            path = generate_notes(transcript, self.config, provider, state.date)
        except Exception as exc:
            log.exception("note generation failed")
            self._fail(
                f"{exc} — your transcript is safe at {self._transcript_path}. "
                "Use Regenerate to retry."
            )
            return self.status()

        with self._lock:
            self._note_path = str(path)
        self._set_phase("done", f"Saved to {Path(path).name}")
        return self.status()

    def _transcribe(self, state) -> str:
        self._set_phase("transcribing", "Transcribing audio")
        transcriber = self.transcriber_factory(self.config)

        def progress(done: int, total: int) -> None:
            with self._lock:
                self._segments_done = done
                self._segments_total = total
            self._set_phase("transcribing", f"Transcribing segment {done} of {total}")

        return combine_transcripts(
            [Path(s) for s in state.segments], transcriber, on_progress=progress
        )

    def _write_transcript(self, state, transcript: str) -> None:
        folder = Path(self.config.data_dir) / "transcripts" / state.date
        folder.mkdir(parents=True, exist_ok=True)
        path = folder / f"{state.filename_base}.txt"
        path.write_text(transcript, encoding="utf-8")
        with self._lock:
            self._transcript_path = str(path)

    def _fail(self, message: str) -> None:
        with self._lock:
            self._error = message
        self._set_phase("failed", message)
