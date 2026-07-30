# beyondMeetings Milestone 4 — The Daily App

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A tray icon and a local page at `localhost:7788` with a Start/Stop button, a live timer, transcription progress, searchable meeting history, and re-run-notes recovery. Plus the rollover timer that finally closes bug B2.

**Architecture:** A `SessionManager` owns the recorder, a rollover worker, and the stop pipeline. Stopping takes minutes, so it runs on a background thread and reports progress through a `JobState` the page polls. Every segment is transcribed as soon as it closes and its transcript cached to disk, so `stop` only has the final segment left — that is what spreads Groq calls across the meeting instead of bursting them at the end.

**Tech Stack:** Existing FastAPI/httpx/pydantic. `pystray` + `pillow` as an **optional** extra — the page works without a tray, and GTK/AppIndicator is fiddly on some desktops.

**Spec:** `docs/superpowers/specs/2026-07-30-beyondmeetings-setup-design.md` §9 (B2), §10
**Tracker:** `PROGRESS.md`

---

## Why B2 is only closing now

`roll_segment()` has existed since milestone 1 and is unit-tested, but nothing ever called it. This milestone adds the timer that does, plus the per-segment transcript cache that makes rollover actually useful. Until both exist, a five-hour meeting still submits five hours of audio in one burst at stop time — which is exactly what broke on 2026-07-08.

---

## File Structure

| File | Responsibility |
|---|---|
| `src/beyondmeetings/segments.py` | Per-segment transcript cache; ordered concatenation; audio cleanup |
| `src/beyondmeetings/session.py` | `JobState`, `SessionManager` — start, stop pipeline, status |
| `src/beyondmeetings/rollover.py` | `RolloverWorker.tick()` — decides when to roll |
| `src/beyondmeetings/history.py` | List meetings from the vault |
| `src/beyondmeetings/tray.py` | Optional pystray icon |
| `src/beyondmeetings/doctor/autostart.py` | `.desktop` autostart entry check |
| `src/beyondmeetings/server.py` | Recording + history + regenerate endpoints; route split |
| `src/beyondmeetings/web/app.{html,css,js}` | The daily page |

---

## Task 1: Segment transcript cache

**Files:**
- Create: `src/beyondmeetings/segments.py`
- Test: `tests/test_segments.py`

Each segment's transcript is cached beside its audio as `<segment>.txt`. `stop` then transcribes only what is missing.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_segments.py
import pytest

from beyondmeetings.segments import (
    cached_transcript, combine_transcripts, discard_audio, transcript_path,
)


class FakeTranscriber:
    def __init__(self, text="fresh"):
        self.text = text
        self.calls = []

    def transcribe_file(self, audio):
        self.calls.append(audio)
        return self.text


def _wav(tmp_path, name):
    path = tmp_path / name
    path.write_bytes(b"RIFF")
    return path


def test_transcript_path_sits_beside_the_audio(tmp_path):
    assert transcript_path(tmp_path / "seg000.wav") == tmp_path / "seg000.txt"


def test_cached_transcript_returns_none_when_absent(tmp_path):
    assert cached_transcript(_wav(tmp_path, "seg000.wav")) is None


def test_cached_transcript_reads_an_existing_file(tmp_path):
    audio = _wav(tmp_path, "seg000.wav")
    transcript_path(audio).write_text("already done")
    assert cached_transcript(audio) == "already done"


def test_combine_uses_the_cache_and_skips_transcription(tmp_path):
    audio = _wav(tmp_path, "seg000.wav")
    transcript_path(audio).write_text("cached text")
    t = FakeTranscriber()
    assert combine_transcripts([audio], t) == "cached text"
    assert t.calls == []


def test_combine_transcribes_and_caches_what_is_missing(tmp_path):
    audio = _wav(tmp_path, "seg000.wav")
    t = FakeTranscriber("brand new")
    assert combine_transcripts([audio], t) == "brand new"
    assert transcript_path(audio).read_text() == "brand new"


def test_combine_preserves_segment_order(tmp_path):
    first, second = _wav(tmp_path, "seg000.wav"), _wav(tmp_path, "seg001.wav")
    transcript_path(first).write_text("one")
    transcript_path(second).write_text("two")
    assert combine_transcripts([first, second], FakeTranscriber()) == "one\ntwo"


def test_combine_reports_progress_per_segment(tmp_path):
    segments = [_wav(tmp_path, f"seg00{i}.wav") for i in range(3)]
    seen = []
    combine_transcripts(
        segments, FakeTranscriber(), on_progress=lambda d, t: seen.append((d, t))
    )
    assert seen == [(1, 3), (2, 3), (3, 3)]


def test_combine_skips_audio_that_no_longer_exists(tmp_path):
    """Earlier segments are deleted after transcription — their .txt remains."""
    missing = tmp_path / "seg000.wav"
    transcript_path(missing).write_text("kept text")
    assert combine_transcripts([missing], FakeTranscriber()) == "kept text"


def test_combine_raises_when_audio_and_cache_are_both_gone(tmp_path):
    with pytest.raises(FileNotFoundError):
        combine_transcripts([tmp_path / "gone.wav"], FakeTranscriber())


def test_discard_audio_removes_the_wav_but_keeps_the_transcript(tmp_path):
    audio = _wav(tmp_path, "seg000.wav")
    transcript_path(audio).write_text("keep me")
    discard_audio(audio)
    assert not audio.exists()
    assert transcript_path(audio).read_text() == "keep me"


def test_discard_audio_is_safe_when_already_gone(tmp_path):
    discard_audio(tmp_path / "never-existed.wav")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_segments.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'beyondmeetings.segments'`

- [ ] **Step 3: Write minimal implementation**

```python
# src/beyondmeetings/segments.py
"""Per-segment transcript caching.

A segment is transcribed as soon as it closes, while the next one records,
and the result is cached beside its audio. By the time the user stops, only
the final segment is usually left. This is what spreads Groq calls across the
real duration of a meeting instead of bursting them at the end.
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
    """Transcribe one segment and cache the result. Returns cached text if any."""
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
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/test_segments.py -v`
Expected: PASS — 11 passed

- [ ] **Step 5: Commit**

```bash
git add src/beyondmeetings/segments.py tests/test_segments.py
git commit -m "feat: per-segment transcript cache"
```

---

## Task 2: Rollover worker

**Files:**
- Create: `src/beyondmeetings/rollover.py`
- Test: `tests/test_rollover.py`

The decision logic is a pure method taking a clock, so it is tested without threads or sleeping.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_rollover.py
from datetime import datetime, timedelta

from beyondmeetings.rollover import RolloverWorker


class FakeRecorder:
    def __init__(self, active=True):
        self.rolled = []
        self.active = active
        self._counter = 0

    def status(self):
        return object() if self.active else None

    def roll_segment(self):
        self._counter += 1
        self.rolled.append(self._counter)
        return f"/data/seg{self._counter - 1:03d}.wav"


def _worker(recorder, transcribed, minutes=50):
    return RolloverWorker(
        recorder=recorder,
        segment_minutes=minutes,
        on_segment_closed=transcribed.append,
    )


def test_does_not_roll_before_the_interval():
    recorder = FakeRecorder()
    worker = _worker(recorder, [])
    start = datetime(2026, 7, 30, 10, 0, 0)
    worker.mark_segment_start(start)
    worker.tick(start + timedelta(minutes=49))
    assert recorder.rolled == []


def test_rolls_once_the_interval_elapses():
    recorder = FakeRecorder()
    worker = _worker(recorder, [])
    start = datetime(2026, 7, 30, 10, 0, 0)
    worker.mark_segment_start(start)
    worker.tick(start + timedelta(minutes=50))
    assert recorder.rolled == [1]


def test_hands_the_finished_segment_to_the_callback():
    recorder = FakeRecorder()
    closed = []
    worker = _worker(recorder, closed)
    start = datetime(2026, 7, 30, 10, 0, 0)
    worker.mark_segment_start(start)
    worker.tick(start + timedelta(minutes=50))
    assert closed == ["/data/seg000.wav"]


def test_rolls_repeatedly_across_a_long_meeting():
    recorder = FakeRecorder()
    worker = _worker(recorder, [])
    now = datetime(2026, 7, 30, 10, 0, 0)
    worker.mark_segment_start(now)
    for _ in range(5):
        now += timedelta(minutes=50)
        worker.tick(now)
    assert recorder.rolled == [1, 2, 3, 4, 5]


def test_timer_resets_after_each_roll():
    recorder = FakeRecorder()
    worker = _worker(recorder, [])
    start = datetime(2026, 7, 30, 10, 0, 0)
    worker.mark_segment_start(start)
    worker.tick(start + timedelta(minutes=50))
    worker.tick(start + timedelta(minutes=99))
    assert recorder.rolled == [1]
    worker.tick(start + timedelta(minutes=100))
    assert recorder.rolled == [1, 2]


def test_does_nothing_when_not_recording():
    recorder = FakeRecorder(active=False)
    worker = _worker(recorder, [])
    start = datetime(2026, 7, 30, 10, 0, 0)
    worker.mark_segment_start(start)
    worker.tick(start + timedelta(minutes=90))
    assert recorder.rolled == []


def test_tick_before_any_start_is_a_no_op():
    recorder = FakeRecorder()
    _worker(recorder, []).tick(datetime(2026, 7, 30, 10, 0, 0))
    assert recorder.rolled == []


def test_a_failing_callback_does_not_stop_future_rolls():
    """A transcription failure mid-meeting must not end segmentation."""
    recorder = FakeRecorder()

    def explode(_):
        raise RuntimeError("groq down")

    worker = RolloverWorker(
        recorder=recorder, segment_minutes=50, on_segment_closed=explode
    )
    now = datetime(2026, 7, 30, 10, 0, 0)
    worker.mark_segment_start(now)
    worker.tick(now + timedelta(minutes=50))
    worker.tick(now + timedelta(minutes=100))
    assert recorder.rolled == [1, 2]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_rollover.py -v`
Expected: FAIL — `ModuleNotFoundError`

- [ ] **Step 3: Write minimal implementation**

```python
# src/beyondmeetings/rollover.py
"""Segment rollover timing.

`tick()` is pure decision logic over an injected clock, so segmentation is
tested without threads or sleeping. The thread that drives it lives in
session.py and does nothing but call tick on a schedule.
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta
from typing import Callable

log = logging.getLogger(__name__)


class RolloverWorker:
    def __init__(
        self,
        recorder,
        segment_minutes: int,
        on_segment_closed: Callable[[str], None],
    ):
        self.recorder = recorder
        self.interval = timedelta(minutes=segment_minutes)
        self.on_segment_closed = on_segment_closed
        self._segment_started: datetime | None = None

    def mark_segment_start(self, when: datetime) -> None:
        self._segment_started = when

    def tick(self, now: datetime) -> None:
        if self._segment_started is None:
            return
        if self.recorder.status() is None:
            return
        if now - self._segment_started < self.interval:
            return

        finished = self.recorder.roll_segment()
        self._segment_started = now

        # A transcription failure must not end segmentation for the rest of
        # the meeting — the segment's audio stays on disk and stop() retries.
        try:
            self.on_segment_closed(finished)
        except Exception:
            log.exception("background transcription failed for %s", finished)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/test_rollover.py -v`
Expected: PASS — 8 passed

- [ ] **Step 5: Commit**

```bash
git add src/beyondmeetings/rollover.py tests/test_rollover.py
git commit -m "feat: segment rollover timing (closes B2)"
```

---

## Task 3: Session manager

**Files:**
- Create: `src/beyondmeetings/session.py`
- Test: `tests/test_session.py`

Owns the recorder and the stop pipeline. Dependencies are injected, and the stop pipeline has a synchronous entry point so tests never touch threads.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_session.py
import pytest

from beyondmeetings.audio.base import RecordingState
from beyondmeetings.config import Config
from beyondmeetings.models import ActionItem, MeetingNote
from beyondmeetings.session import SessionManager
from beyondmeetings.vault.scaffold import scaffold_vault


class FakeRecorder:
    def __init__(self, tmp_path):
        self.tmp_path = tmp_path
        self.state = None
        self.stopped = False

    def start(self, name):
        seg = self.tmp_path / "seg000.wav"
        seg.write_bytes(b"RIFF")
        self.state = RecordingState(
            name=name, filename_base="2026-07-30_10-00_test", date="2026-07-30",
            pid=1, module_ids=[1], segments=[str(seg)],
            started_at="2026-07-30T10:00:00",
        )
        return self.state

    def stop(self):
        if self.state is None:
            raise RuntimeError("no active recording")
        self.stopped = True
        state, self.state = self.state, None
        return state

    def status(self):
        return self.state

    def roll_segment(self):
        return self.state.segments[-1]


class FakeTranscriber:
    def transcribe_file(self, audio):
        return "the transcript"


class FakeProvider:
    def __init__(self, note=None, error=None):
        self.note = note
        self.error = error

    def analyse(self, prompt, valid_candidate_ids=None):
        if self.error:
            raise self.error
        return self.note


def _note():
    return MeetingNote(
        title="Test Meeting", date="2026-07-30", tags=["meeting"],
        executive_summary="We tested.", one_line_summary="Tested",
        action_items=[ActionItem(task="Ship it", priority="HIGH")],
    )


@pytest.fixture
def manager(tmp_path):
    vault = tmp_path / "vault"
    vault.mkdir()
    scaffold_vault(vault)
    data = tmp_path / "data"
    data.mkdir()
    config = Config(vault_path=str(vault), data_dir=str(data))
    return SessionManager(
        config=config,
        recorder=FakeRecorder(tmp_path),
        transcriber_factory=lambda c: FakeTranscriber(),
        provider_factory=lambda c: FakeProvider(_note()),
    )


def test_starts_idle(manager):
    assert manager.status()["phase"] == "idle"
    assert manager.status()["recording"] is False


def test_start_reports_recording(manager):
    manager.start("Test Meeting")
    status = manager.status()
    assert status["phase"] == "recording"
    assert status["recording"] is True
    assert status["name"] == "Test Meeting"


def test_start_twice_is_refused(manager):
    manager.start("One")
    with pytest.raises(RuntimeError, match="already recording"):
        manager.start("Two")


def test_status_reports_elapsed_seconds(manager):
    manager.start("Test")
    assert manager.status()["elapsed_seconds"] >= 0


def test_stop_without_recording_is_refused(manager):
    with pytest.raises(RuntimeError, match="no active recording"):
        manager.run_stop()


def test_stop_writes_the_note_and_reaches_done(manager, tmp_path):
    manager.start("Test Meeting")
    manager.run_stop()
    status = manager.status()
    assert status["phase"] == "done"
    assert status["note_path"].endswith("Test Meeting.md")
    assert (tmp_path / "vault" / "Meetings" / "2026-07-30" / "Test Meeting.md").is_file()


def test_stop_writes_the_transcript_to_the_data_dir(manager, tmp_path):
    manager.start("Test Meeting")
    manager.run_stop()
    transcripts = list((tmp_path / "data" / "transcripts").rglob("*.txt"))
    assert len(transcripts) == 1
    assert transcripts[0].read_text() == "the transcript"


def test_stop_adds_tasks_to_the_board(manager, tmp_path):
    manager.start("Test")
    manager.run_stop()
    board = (tmp_path / "vault" / "Tasks" / "Task Board.md").read_text()
    assert "**==Ship it==**" in board


def test_stop_records_progress_phases(manager):
    seen = []
    manager.on_phase_change = seen.append
    manager.start("Test")
    manager.run_stop()
    assert "transcribing" in seen
    assert "analysing" in seen
    assert "done" in seen


def test_a_failing_provider_surfaces_the_error_not_a_crash(tmp_path):
    vault = tmp_path / "vault"
    vault.mkdir()
    scaffold_vault(vault)
    data = tmp_path / "data"
    data.mkdir()
    manager = SessionManager(
        config=Config(vault_path=str(vault), data_dir=str(data)),
        recorder=FakeRecorder(tmp_path),
        transcriber_factory=lambda c: FakeTranscriber(),
        provider_factory=lambda c: FakeProvider(error=RuntimeError("api down")),
    )
    manager.start("Test")
    manager.run_stop()
    status = manager.status()
    assert status["phase"] == "failed"
    assert "api down" in status["error"]


def test_the_transcript_survives_a_provider_failure(manager_factory=None):
    """Losing an hour of audio to a note-generation error is unacceptable."""
    import tempfile
    from pathlib import Path

    tmp_path = Path(tempfile.mkdtemp())
    vault = tmp_path / "vault"
    vault.mkdir()
    scaffold_vault(vault)
    data = tmp_path / "data"
    data.mkdir()
    manager = SessionManager(
        config=Config(vault_path=str(vault), data_dir=str(data)),
        recorder=FakeRecorder(tmp_path),
        transcriber_factory=lambda c: FakeTranscriber(),
        provider_factory=lambda c: FakeProvider(error=RuntimeError("api down")),
    )
    manager.start("Test")
    manager.run_stop()
    assert list((data / "transcripts").rglob("*.txt"))
    assert manager.status()["transcript_path"]


def test_can_start_again_after_a_completed_meeting(manager):
    manager.start("First")
    manager.run_stop()
    manager.start("Second")
    assert manager.status()["name"] == "Second"


def test_can_start_again_after_a_failed_stop(tmp_path):
    vault = tmp_path / "vault"
    vault.mkdir()
    scaffold_vault(vault)
    data = tmp_path / "data"
    data.mkdir()
    manager = SessionManager(
        config=Config(vault_path=str(vault), data_dir=str(data)),
        recorder=FakeRecorder(tmp_path),
        transcriber_factory=lambda c: FakeTranscriber(),
        provider_factory=lambda c: FakeProvider(error=RuntimeError("boom")),
    )
    manager.start("First")
    manager.run_stop()
    manager.start("Second")
    assert manager.status()["recording"] is True
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_session.py -v`
Expected: FAIL — `ModuleNotFoundError`

- [ ] **Step 3: Write minimal implementation**

```python
# src/beyondmeetings/session.py
"""Recording session lifecycle and the stop pipeline.

Stopping takes minutes, so `stop()` spawns a thread and the page polls
`status()`. `run_stop()` is the synchronous body — tests call it directly and
never touch threads.

The transcript is written to disk *before* the LLM is called. Losing an hour
of audio because note generation failed would be unacceptable; a saved
transcript can always be re-run.
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
            }

    # ---------- start ----------

    def start(self, name: str = "") -> dict:
        if self.recorder.status() is not None:
            raise RuntimeError("already recording")

        name = name.strip() or self.clock().strftime("recording-%H-%M")
        with self._lock:
            self._error = None
            self._note_path = None
            self._transcript_path = None
            self._segments_done = 0
            self._segments_total = 0
            self._name = name
            self._started_at = self.clock()

        self.recorder.start(name)
        self._rollover.mark_segment_start(self._started_at)
        self._set_phase("recording")
        self._start_ticker()
        return self.status()

    def _start_ticker(self) -> None:
        self._ticker_stop.clear()

        def loop():
            while not self._ticker_stop.wait(TICK_SECONDS):
                try:
                    self._rollover.tick(self.clock())
                except Exception:
                    log.exception("rollover tick failed")

        self._ticker = threading.Thread(target=loop, daemon=True)
        self._ticker.start()

    def _segment_closed(self, audio: str) -> None:
        """Transcribe a closed segment while the next one records."""
        transcriber = self.transcriber_factory(self.config)
        transcribe_segment(Path(audio), transcriber)
        # Audio for an earlier segment is no longer needed once cached.
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

        self._ticker_stop.set()
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
                f"{exc}  Your transcript is safe at {self._transcript_path} — "
                "use Regenerate to retry."
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
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/test_session.py -v`
Expected: PASS — 13 passed

- [ ] **Step 5: Commit**

```bash
git add src/beyondmeetings/session.py tests/test_session.py
git commit -m "feat: session manager with progress-reporting stop pipeline"
```

---

## Task 4: Meeting history

**Files:**
- Create: `src/beyondmeetings/history.py`
- Test: `tests/test_history.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_history.py
from beyondmeetings.history import list_meetings


def _note(vault, day, title, summary="A summary.", tag="Acme"):
    folder = vault / "Meetings" / day
    folder.mkdir(parents=True, exist_ok=True)
    (folder / f"{title}.md").write_text(
        f"---\ntags:\n  - meeting\n  - {tag}\ndate: {day}\n---\n\n"
        f"# {title}\n\n## Executive Summary\n{summary}\n\n"
        f"## Action Items\n- [ ] **One** — **Sam**\n- [ ] **Two**\n"
    )


def test_empty_vault_returns_nothing(tmp_path):
    assert list_meetings(tmp_path) == []


def test_lists_a_meeting_with_its_metadata(tmp_path):
    _note(tmp_path, "2026-07-30", "Standup", summary="We synced.")
    row = list_meetings(tmp_path)[0]
    assert row["title"] == "Standup"
    assert row["date"] == "2026-07-30"
    assert row["summary"] == "We synced."
    assert row["project"] == "Acme"
    assert row["link"] == "Meetings/2026-07-30/Standup"


def test_counts_action_items(tmp_path):
    _note(tmp_path, "2026-07-30", "Standup")
    assert list_meetings(tmp_path)[0]["tasks"] == 2


def test_newest_first(tmp_path):
    for day in ("2026-07-28", "2026-07-30", "2026-07-29"):
        _note(tmp_path, day, f"Meeting {day}")
    dates = [m["date"] for m in list_meetings(tmp_path)]
    assert dates == sorted(dates, reverse=True)


def test_respects_the_limit(tmp_path):
    for i in range(1, 8):
        _note(tmp_path, f"2026-07-0{i}", f"Meeting {i}")
    assert len(list_meetings(tmp_path, limit=3)) == 3


def test_ignores_non_date_folders(tmp_path):
    (tmp_path / "Meetings" / "Templates").mkdir(parents=True)
    (tmp_path / "Meetings" / "Templates" / "Blank.md").write_text("# Blank")
    assert list_meetings(tmp_path) == []


def test_handles_a_note_with_no_summary(tmp_path):
    folder = tmp_path / "Meetings" / "2026-07-30"
    folder.mkdir(parents=True)
    (folder / "Bare.md").write_text("# Bare\n")
    row = list_meetings(tmp_path)[0]
    assert row["title"] == "Bare"
    assert row["summary"] == ""


def test_marks_informal_meetings_with_no_tasks(tmp_path):
    folder = tmp_path / "Meetings" / "2026-07-30"
    folder.mkdir(parents=True)
    (folder / "Catch-up.md").write_text(
        "---\ntags:\n  - meeting\ndate: 2026-07-30\n---\n\n"
        "# Catch-up\n\n## Action Items\nNone recorded.\n"
    )
    assert list_meetings(tmp_path)[0]["tasks"] == 0


def test_missing_meetings_directory_is_not_an_error(tmp_path):
    assert list_meetings(tmp_path / "nope") == []
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_history.py -v`
Expected: FAIL — `ModuleNotFoundError`

- [ ] **Step 3: Write minimal implementation**

```python
# src/beyondmeetings/history.py
"""Read the vault to list past meetings for the app page."""
from __future__ import annotations

import re
from pathlib import Path

from .vault.paths import meetings_dir

DATE_FOLDER = re.compile(r"^\d{4}-\d{2}-\d{2}$")
SUMMARY = re.compile(
    r"^## Executive Summary\s*\n(.+?)(?=\n##|\n---|\Z)", re.DOTALL | re.MULTILINE
)
TAG_LINE = re.compile(r"^\s+- (.+)$", re.MULTILINE)
TASK_LINE = re.compile(r"^- \[ \] ", re.MULTILINE)


def _read(path: Path, folder: str) -> dict:
    text = path.read_text(encoding="utf-8", errors="replace")
    front = text.split("---", 2)[1] if text.startswith("---") else ""
    tags = [t.strip() for t in TAG_LINE.findall(front) if t.strip() != "meeting"]
    match = SUMMARY.search(text)
    return {
        "title": path.stem,
        "date": folder,
        "summary": match.group(1).strip() if match else "",
        "project": tags[0] if tags else "",
        "tasks": len(TASK_LINE.findall(text)),
        "link": f"Meetings/{folder}/{path.stem}",
    }


def list_meetings(vault: Path, limit: int = 100) -> list[dict]:
    root = meetings_dir(Path(vault))
    if not root.is_dir():
        return []

    found: list[dict] = []
    for folder in sorted(root.iterdir(), reverse=True):
        if not folder.is_dir() or not DATE_FOLDER.match(folder.name):
            continue
        for note in sorted(folder.glob("*.md")):
            found.append(_read(note, folder.name))
            if len(found) >= limit:
                return found
    return found
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/test_history.py -v`
Expected: PASS — 9 passed

- [ ] **Step 5: Commit**

```bash
git add src/beyondmeetings/history.py tests/test_history.py
git commit -m "feat: meeting history listing"
```

---

## Task 5: Server endpoints and route split

**Files:**
- Modify: `src/beyondmeetings/server.py`
- Test: `tests/test_server_app.py`

`/` becomes the app; the wizard stays at `/setup`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_server_app.py
import pytest
from fastapi.testclient import TestClient

from beyondmeetings.config import Config
from beyondmeetings.server import create_app
from beyondmeetings.vault.scaffold import scaffold_vault


class FakeSession:
    def __init__(self):
        self.started = None
        self.stopped = False
        self.state = {"phase": "idle", "recording": False, "name": "",
                      "elapsed_seconds": 0, "segments_done": 0,
                      "segments_total": 0, "note_path": None,
                      "transcript_path": None, "error": None, "detail": ""}

    def start(self, name=""):
        self.started = name
        self.state = {**self.state, "phase": "recording",
                      "recording": True, "name": name or "recording-10-00"}
        return self.state

    def stop(self):
        self.stopped = True
        self.state = {**self.state, "phase": "stopping", "recording": False}
        return self.state

    def status(self):
        return self.state


@pytest.fixture
def app_and_session(tmp_path):
    vault = tmp_path / "vault"
    vault.mkdir()
    scaffold_vault(vault)
    session = FakeSession()
    app = create_app(
        config=Config(vault_path=str(vault)),
        config_path=tmp_path / "config.toml",
        checks_factory=lambda c: [],
        session=session,
    )
    return TestClient(app), session, vault


def test_root_serves_the_app_page(app_and_session):
    client, _, _ = app_and_session
    response = client.get("/")
    assert response.status_code == 200
    assert "app.css" in response.text


def test_setup_still_serves_the_wizard(app_and_session):
    client, _, _ = app_and_session
    assert "setup.css" in client.get("/setup").text


def test_app_assets_are_served(app_and_session):
    client, _, _ = app_and_session
    assert client.get("/app.css").status_code == 200
    assert client.get("/app.js").status_code == 200


def test_recording_status_is_exposed(app_and_session):
    client, _, _ = app_and_session
    assert client.get("/api/recording").json()["phase"] == "idle"


def test_start_passes_the_name_through(app_and_session):
    client, session, _ = app_and_session
    body = client.post("/api/recording/start", json={"name": "Kickoff"}).json()
    assert session.started == "Kickoff"
    assert body["recording"] is True


def test_start_without_a_name_is_allowed(app_and_session):
    client, session, _ = app_and_session
    assert client.post("/api/recording/start", json={}).status_code == 200
    assert session.started == ""


def test_stop_dispatches_to_the_session(app_and_session):
    client, session, _ = app_and_session
    client.post("/api/recording/start", json={"name": "x"})
    client.post("/api/recording/stop", json={})
    assert session.stopped is True


def test_start_while_recording_returns_409(app_and_session, monkeypatch):
    client, session, _ = app_and_session

    def boom(name=""):
        raise RuntimeError("already recording")

    monkeypatch.setattr(session, "start", boom)
    response = client.post("/api/recording/start", json={})
    assert response.status_code == 409
    assert "already recording" in response.json()["detail"]


def test_stop_without_recording_returns_409(app_and_session, monkeypatch):
    client, session, _ = app_and_session

    def boom():
        raise RuntimeError("no active recording")

    monkeypatch.setattr(session, "stop", boom)
    assert client.post("/api/recording/stop", json={}).status_code == 409


def test_history_lists_vault_meetings(app_and_session):
    client, _, vault = app_and_session
    folder = vault / "Meetings" / "2026-07-30"
    folder.mkdir(parents=True)
    (folder / "Standup.md").write_text(
        "---\ntags:\n  - meeting\ndate: 2026-07-30\n---\n\n"
        "# Standup\n\n## Executive Summary\nWe synced.\n"
    )
    rows = client.get("/api/meetings").json()["meetings"]
    assert rows[0]["title"] == "Standup"


def test_regenerate_requires_an_existing_transcript(app_and_session):
    client, _, _ = app_and_session
    response = client.post("/api/regenerate", json={"transcript": "/nope.txt"})
    assert response.status_code == 404


def test_regenerate_writes_a_note(app_and_session, tmp_path, monkeypatch):
    client, _, vault = app_and_session
    transcript = tmp_path / "t.txt"
    transcript.write_text("we discussed things")

    from beyondmeetings import server as server_mod
    from beyondmeetings.models import MeetingNote

    monkeypatch.setattr(
        server_mod, "build_provider",
        lambda cfg: type("P", (), {"analyse": lambda self, p, ids=None: MeetingNote(
            title="Regenerated", date="2026-07-30",
            executive_summary="x", one_line_summary="x")})(),
    )
    body = client.post("/api/regenerate", json={"transcript": str(transcript)}).json()
    assert body["note_path"].endswith("Regenerated.md")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_server_app.py -v`
Expected: FAIL — `TypeError: create_app() got an unexpected keyword argument 'session'`

- [ ] **Step 3: Write minimal implementation**

In `server.py`: add imports for `history`, `build_provider`, `generate_notes`, `SessionManager`; accept a `session` argument; split the routes.

```python
class StartRequest(BaseModel, extra="forbid"):
    name: str = ""


class RegenerateRequest(BaseModel, extra="forbid"):
    transcript: str
```

Replace the single page route with:

```python
    @app.get("/", response_class=HTMLResponse)
    def app_page():
        return (WEB_DIR / "app.html").read_text(encoding="utf-8")

    @app.get("/setup", response_class=HTMLResponse)
    def setup_page():
        return (WEB_DIR / "setup.html").read_text(encoding="utf-8")

    @app.get("/{asset}.css")
    def css(asset: str):
        path = WEB_DIR / f"{asset}.css"
        if not path.is_file():
            raise HTTPException(status_code=404, detail="not found")
        return Response(path.read_text(encoding="utf-8"), media_type="text/css")

    @app.get("/{asset}.js")
    def js(asset: str):
        path = WEB_DIR / f"{asset}.js"
        if not path.is_file():
            raise HTTPException(status_code=404, detail="not found")
        return Response(
            path.read_text(encoding="utf-8"), media_type="application/javascript"
        )
```

Add the recording, history and regenerate endpoints:

```python
    @app.get("/api/recording")
    def recording_status():
        return _session().status()

    @app.post("/api/recording/start")
    def recording_start(request: StartRequest):
        try:
            return _session().start(request.name)
        except RuntimeError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    @app.post("/api/recording/stop")
    def recording_stop():
        try:
            return _session().stop()
        except RuntimeError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    @app.get("/api/meetings")
    def meetings():
        vault = state["config"].vault_path
        return {"meetings": list_meetings(Path(vault)) if vault else []}

    @app.post("/api/regenerate")
    def regenerate(request: RegenerateRequest):
        path = Path(request.transcript).expanduser()
        if not path.is_file():
            raise HTTPException(status_code=404, detail=f"No transcript at {path}")
        try:
            written = generate_notes(
                path.read_text(encoding="utf-8"),
                state["config"],
                build_provider(state["config"]),
            )
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return {"note_path": str(written)}
```

`_session()` lazily builds a real `SessionManager` when none was injected:

```python
    def _session():
        if state.get("session") is None:
            from .audio.pipewire import PipeWireRecorder
            from .llm.factory import build_provider as provider_factory
            from .transcribe.factory import build_transcriber

            cfg = state["config"]
            state["session"] = SessionManager(
                config=cfg,
                recorder=PipeWireRecorder(
                    Path(cfg.data_dir), segment_minutes=cfg.segment_minutes
                ),
                transcriber_factory=build_transcriber,
                provider_factory=provider_factory,
            )
        return state["session"]
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/test_server_app.py tests/test_server.py -v`
Expected: PASS — the existing `test_setup_page_is_served` must be updated: `/` now serves the app, not the wizard.

- [ ] **Step 5: Commit**

```bash
git add src/beyondmeetings/server.py tests/test_server_app.py tests/test_server.py
git commit -m "feat: recording, history and regenerate endpoints"
```

---

## Task 6: The app page

**Files:**
- Create: `src/beyondmeetings/web/app.html`, `app.css`, `app.js`

Big Start/Stop control, live timer, transcription progress, searchable history, and a Regenerate action when note generation failed.

- [ ] **Step 1: Write `app.html`**

```html
<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>beyondMeetings</title>
  <link rel="stylesheet" href="/app.css">
</head>
<body>
  <main>
    <header class="bar">
      <strong>beyondMeetings</strong>
      <a href="/setup" class="quiet">Settings</a>
    </header>

    <section class="control" id="control">
      <button id="record" class="record">Start</button>
      <div class="controlText">
        <div class="state" id="state">Ready to record</div>
        <div class="timer" id="timer" hidden>00:00</div>
        <div class="detail" id="detail"></div>
        <input id="name" class="nameInput" placeholder="Meeting name (optional)">
      </div>
    </section>

    <section class="alert" id="alert" hidden>
      <div class="alertText" id="alertText"></div>
      <button id="retry" class="btn" hidden>Regenerate notes</button>
    </section>

    <section>
      <div class="listHead">
        <h2>Meetings</h2>
        <input id="search" class="search" placeholder="Search…" aria-label="Search meetings">
      </div>
      <div id="list" class="list"></div>
      <p class="empty" id="empty" hidden>No meetings yet.</p>
    </section>
  </main>
  <script src="/app.js"></script>
</body>
</html>
```

- [ ] **Step 2: Write `app.css`**

Reuse the wizard's variable block, then add:

```css
:root {
  --bg: #fbfbfd; --fg: #16161a; --muted: #6b6b76;
  --line: #e3e3e8; --card: #fff;
  --accent: #6366f1; --ok: #16a34a; --bad: #dc2626;
}
@media (prefers-color-scheme: dark) {
  :root {
    --bg: #131316; --fg: #ededf0; --muted: #9a9aa5;
    --line: #2a2a31; --card: #1b1b20;
  }
}
* { box-sizing: border-box; }
body {
  margin: 0; padding: 32px 20px; background: var(--bg); color: var(--fg);
  font: 15px/1.55 ui-sans-serif, system-ui, -apple-system, sans-serif;
}
main { max-width: 760px; margin: 0 auto; }
.bar {
  display: flex; align-items: center; justify-content: space-between;
  margin-bottom: 24px; font-size: 15px;
}
.quiet { color: var(--muted); text-decoration: none; font-size: 13px; }
.quiet:hover { color: var(--accent); }
.control {
  display: flex; align-items: center; gap: 20px; padding: 20px;
  border: 1px solid var(--line); border-radius: 12px; background: var(--card);
}
.record {
  width: 88px; height: 88px; border-radius: 50%; flex: none; cursor: pointer;
  border: 0; background: var(--accent); color: #fff;
  font: inherit; font-size: 14px; font-weight: 700; letter-spacing: .03em;
  transition: background .2s ease;
}
.record:hover:not(:disabled) { filter: brightness(1.08); }
.record:disabled { opacity: .6; cursor: default; }
.record.stop { background: var(--bad); }
.controlText { flex: 1; min-width: 0; }
.state { font-weight: 600; }
.timer {
  font-size: 26px; font-weight: 700; font-variant-numeric: tabular-nums;
  margin: 2px 0;
}
.detail { color: var(--muted); font-size: 13px; }
.nameInput {
  font: inherit; font-size: 13px; margin-top: 10px; width: 100%;
  padding: 7px 10px; border-radius: 7px;
  border: 1px solid var(--line); background: var(--bg); color: var(--fg);
}
.alert {
  margin-top: 14px; padding: 14px 16px; border-radius: 10px;
  border: 1px solid var(--bad);
  background: color-mix(in srgb, var(--bad) 8%, transparent);
  display: flex; align-items: center; gap: 12px; flex-wrap: wrap;
}
.alertText { flex: 1; font-size: 13px; min-width: 200px; }
.btn {
  font: inherit; font-size: 13px; padding: 6px 13px; border-radius: 7px;
  border: 1px solid var(--line); background: var(--card); color: var(--fg);
  cursor: pointer;
}
.btn:hover { border-color: var(--accent); }
.listHead {
  display: flex; align-items: center; justify-content: space-between;
  gap: 12px; margin: 30px 0 12px;
}
.listHead h2 { font-size: 17px; margin: 0; }
.search {
  font: inherit; font-size: 13px; padding: 6px 10px; border-radius: 7px;
  border: 1px solid var(--line); background: var(--card); color: var(--fg);
  min-width: 180px;
}
.list {
  border: 1px solid var(--line); border-radius: 12px; overflow: hidden;
  background: var(--card);
}
.item { padding: 13px 16px; border-bottom: 1px solid var(--line); }
.item:last-child { border-bottom: 0; }
.itemTop {
  display: flex; align-items: baseline; gap: 8px; flex-wrap: wrap;
}
.itemTitle { font-weight: 600; font-size: 14px; }
.pill {
  font-size: 10.5px; color: var(--muted); border: 1px solid var(--line);
  padding: 1px 7px; border-radius: 20px;
}
.itemSummary {
  color: var(--muted); font-size: 13px; margin-top: 3px;
  display: -webkit-box; -webkit-line-clamp: 2; -webkit-box-orient: vertical;
  overflow: hidden;
}
.empty { color: var(--muted); font-size: 13px; text-align: center; padding: 20px; }
@media (max-width: 560px) {
  .control { flex-direction: column; align-items: flex-start; }
}
```

- [ ] **Step 3: Write `app.js`**

```javascript
const $ = (id) => document.getElementById(id);
let meetings = [];
let polling = null;

async function api(path, body) {
  const options = body === undefined ? {} : {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify(body),
  };
  const res = await fetch(path, options);
  if (!res.ok) {
    let detail = `${res.status}`;
    try { detail = (await res.json()).detail || detail; } catch (_) {}
    throw new Error(detail);
  }
  return res.json();
}

function clock(seconds) {
  const h = Math.floor(seconds / 3600);
  const m = Math.floor((seconds % 3600) / 60);
  const s = seconds % 60;
  const pad = (n) => String(n).padStart(2, "0");
  return h ? `${h}:${pad(m)}:${pad(s)}` : `${pad(m)}:${pad(s)}`;
}

const LABELS = {
  idle: "Ready to record",
  recording: "Recording",
  stopping: "Stopping…",
  transcribing: "Transcribing…",
  analysing: "Writing notes…",
  done: "Notes saved",
  failed: "Something went wrong",
};

function renderStatus(s) {
  const busy = ["stopping", "transcribing", "analysing"].includes(s.phase);
  const btn = $("record");

  $("state").textContent = s.recording && s.name
    ? `Recording — ${s.name}`
    : LABELS[s.phase] || s.phase;
  $("detail").textContent = s.detail || "";
  $("timer").hidden = !s.recording;
  if (s.recording) $("timer").textContent = clock(s.elapsed_seconds);

  btn.disabled = busy;
  btn.textContent = busy ? "…" : s.recording ? "Stop" : "Start";
  btn.classList.toggle("stop", s.recording);
  $("name").hidden = s.recording || busy;

  const failed = s.phase === "failed";
  $("alert").hidden = !failed;
  if (failed) {
    $("alertText").textContent = s.error || "Note generation failed.";
    $("retry").hidden = !s.transcript_path;
    $("retry").dataset.transcript = s.transcript_path || "";
  }

  // Poll while anything is in flight; idle otherwise.
  const shouldPoll = s.recording || busy;
  if (shouldPoll && !polling) polling = setInterval(refresh, 1000);
  if (!shouldPoll && polling) { clearInterval(polling); polling = null; }
  if (s.phase === "done") loadMeetings();
}

function renderMeetings() {
  const query = $("search").value.trim().toLowerCase();
  const rows = query
    ? meetings.filter((m) =>
        `${m.title} ${m.summary} ${m.project}`.toLowerCase().includes(query))
    : meetings;

  $("empty").hidden = rows.length > 0;
  $("empty").textContent = meetings.length
    ? "Nothing matches that search."
    : "No meetings yet.";

  $("list").replaceChildren(...rows.map((m) => {
    const item = document.createElement("div");
    item.className = "item";

    const top = document.createElement("div");
    top.className = "itemTop";
    const title = document.createElement("span");
    title.className = "itemTitle";
    title.textContent = m.title;
    top.append(title);
    for (const text of [m.date, m.project, m.tasks ? `${m.tasks} tasks` : "no tasks"]) {
      if (!text) continue;
      const pill = document.createElement("span");
      pill.className = "pill";
      pill.textContent = text;
      top.append(pill);
    }
    item.append(top);

    if (m.summary) {
      const summary = document.createElement("div");
      summary.className = "itemSummary";
      summary.textContent = m.summary;
      item.append(summary);
    }
    return item;
  }));
}

async function refresh() {
  try { renderStatus(await api("/api/recording")); }
  catch (err) { $("detail").textContent = `Lost the server: ${err.message}`; }
}

async function loadMeetings() {
  try {
    meetings = (await api("/api/meetings")).meetings;
    renderMeetings();
  } catch (_) { /* history is not critical */ }
}

$("record").onclick = async () => {
  const btn = $("record");
  btn.disabled = true;
  try {
    const current = await api("/api/recording");
    renderStatus(current.recording
      ? await api("/api/recording/stop", {})
      : await api("/api/recording/start", { name: $("name").value }));
  } catch (err) {
    btn.disabled = false;
    window.alert(err.message);
  }
};

$("retry").onclick = async (event) => {
  const btn = event.currentTarget;
  btn.disabled = true;
  btn.textContent = "Working…";
  try {
    await api("/api/regenerate", { transcript: btn.dataset.transcript });
    await loadMeetings();
    await refresh();
  } catch (err) {
    window.alert(`Could not regenerate: ${err.message}`);
  } finally {
    btn.disabled = false;
    btn.textContent = "Regenerate notes";
  }
};

$("search").oninput = renderMeetings;
$("name").onkeydown = (e) => { if (e.key === "Enter") $("record").click(); };

refresh();
loadMeetings();
```

- [ ] **Step 4: Verify**

Run: `.venv/bin/python -m pytest tests/test_server_app.py -v`
Expected: PASS. Then boot the app and confirm the page renders, Start/Stop toggles, and history lists real vault notes.

- [ ] **Step 5: Commit**

```bash
git add src/beyondmeetings/web
git commit -m "feat: daily app page with history and recovery"
```

---

## Task 7: Tray and autostart

**Files:**
- Create: `src/beyondmeetings/tray.py`, `src/beyondmeetings/doctor/autostart.py`
- Modify: `pyproject.toml`, `src/beyondmeetings/cli.py`, `src/beyondmeetings/doctor/registry.py`
- Test: `tests/test_tray.py`, `tests/test_doctor_autostart.py`

`pystray` is an **optional** extra: it pulls a GTK/AppIndicator stack that is fiddly on some desktops, and the page works fine without it.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_tray.py
import pytest

from beyondmeetings.tray import TRAY_HINT, build_icon_image, tray_available


def test_reports_availability_honestly():
    assert isinstance(tray_available(), bool)


def test_hint_names_the_extra():
    assert "beyondmeetings[tray]" in TRAY_HINT


def test_icon_image_is_square_when_pillow_is_present():
    pytest.importorskip("PIL")
    image = build_icon_image(recording=False)
    assert image.size[0] == image.size[1]


def test_recording_icon_differs_from_idle():
    pytest.importorskip("PIL")
    idle = build_icon_image(recording=False).tobytes()
    live = build_icon_image(recording=True).tobytes()
    assert idle != live


def test_run_tray_without_pystray_raises_the_hint(monkeypatch):
    import beyondmeetings.tray as tray_mod
    monkeypatch.setattr(tray_mod, "pystray", None)
    with pytest.raises(RuntimeError, match=r"beyondmeetings\[tray\]"):
        tray_mod.run_tray("http://127.0.0.1:7788")
```

```python
# tests/test_doctor_autostart.py
from beyondmeetings.config import Config
from beyondmeetings.doctor.autostart import AutostartCheck


def test_missing_when_no_desktop_entry(tmp_path):
    assert AutostartCheck(Config(), home=tmp_path).detect().status == "missing"


def test_fix_writes_a_desktop_entry(tmp_path):
    check = AutostartCheck(Config(), home=tmp_path)
    assert check.fix().status == "ok"
    entry = tmp_path / ".config" / "autostart" / "beyondmeetings.desktop"
    assert entry.is_file()
    assert "beyondmeetings" in entry.read_text()


def test_entry_is_a_valid_desktop_file(tmp_path):
    AutostartCheck(Config(), home=tmp_path).fix()
    text = (tmp_path / ".config" / "autostart" / "beyondmeetings.desktop").read_text()
    assert text.startswith("[Desktop Entry]")
    assert "Type=Application" in text
    assert "Exec=" in text


def test_ok_once_written(tmp_path):
    check = AutostartCheck(Config(), home=tmp_path)
    check.fix()
    assert check.detect().status == "ok"


def test_autostart_is_optional(tmp_path):
    assert AutostartCheck(Config(), home=tmp_path).required is False


def test_fix_is_idempotent(tmp_path):
    check = AutostartCheck(Config(), home=tmp_path)
    check.fix()
    check.fix()
    entries = list((tmp_path / ".config" / "autostart").glob("*.desktop"))
    assert len(entries) == 1
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_tray.py tests/test_doctor_autostart.py -v`
Expected: FAIL — `ModuleNotFoundError`

- [ ] **Step 3: Write minimal implementation**

```python
# src/beyondmeetings/tray.py
"""Optional system-tray icon.

pystray pulls a GTK/AppIndicator stack that behaves differently across
desktop environments, so it is an extra rather than a hard dependency. The
app page at localhost:7788 is fully usable without it.
"""
from __future__ import annotations

import threading
import webbrowser

try:
    import pystray
except Exception:  # ImportError, or a missing display backend
    pystray = None

try:
    from PIL import Image, ImageDraw
except Exception:
    Image = ImageDraw = None

TRAY_HINT = (
    "The tray needs extra packages. Install them with:\n"
    "  pip install 'beyondmeetings[tray]'\n"
    "The app page at http://127.0.0.1:7788 works without it."
)

SIZE = 64


def tray_available() -> bool:
    return pystray is not None and Image is not None


def build_icon_image(recording: bool = False):
    if Image is None:
        raise RuntimeError(TRAY_HINT)
    image = Image.new("RGBA", (SIZE, SIZE), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    colour = (220, 38, 38, 255) if recording else (99, 102, 241, 255)
    draw.ellipse([6, 6, SIZE - 6, SIZE - 6], fill=colour)
    if recording:
        draw.rectangle([24, 24, SIZE - 24, SIZE - 24], fill=(255, 255, 255, 255))
    return image


def run_tray(url: str, session=None) -> None:
    """Blocking. Runs the tray icon until quit."""
    if not tray_available():
        raise RuntimeError(TRAY_HINT)

    def open_app(_icon=None, _item=None):
        webbrowser.open(url)

    def toggle(icon, _item=None):
        if session is None:
            open_app()
            return
        try:
            if session.status()["recording"]:
                session.stop()
            else:
                session.start("")
        except RuntimeError:
            pass
        icon.icon = build_icon_image(session.status()["recording"])

    def refresh(icon):
        icon.visible = True
        while True:
            if session is not None:
                icon.icon = build_icon_image(session.status()["recording"])
            threading.Event().wait(2)

    menu_items = [pystray.MenuItem("Open beyondMeetings", open_app)]
    if session is not None:
        menu_items.insert(0, pystray.MenuItem("Start / stop recording", toggle))
    menu_items.append(pystray.MenuItem("Quit", lambda icon, _=None: icon.stop()))

    icon = pystray.Icon(
        "beyondmeetings",
        build_icon_image(False),
        "beyondMeetings",
        pystray.Menu(*menu_items),
    )
    icon.run(setup=refresh if session is not None else None)
```

```python
# src/beyondmeetings/doctor/autostart.py
"""Launch beyondMeetings at login via a freedesktop autostart entry."""
from __future__ import annotations

from pathlib import Path

from ..config import Config
from .base import Check, CheckResult

ENTRY = """[Desktop Entry]
Type=Application
Name=beyondMeetings
Comment=Meeting recorder and note generator
Exec=beyondmeetings serve
Terminal=false
X-GNOME-Autostart-enabled=true
"""


class AutostartCheck(Check):
    id = "autostart"
    label = "Start at login"
    description = "Runs beyondMeetings in the background when you log in."
    required = False

    def __init__(self, config: Config, home: Path | None = None):
        self.config = config
        self.home = Path(home or Path.home())

    @property
    def _entry_path(self) -> Path:
        return self.home / ".config" / "autostart" / "beyondmeetings.desktop"

    def detect(self) -> CheckResult:
        if self._entry_path.is_file():
            return CheckResult(status="ok", detail=str(self._entry_path))
        return CheckResult(status="missing", detail="Not set up.")

    @property
    def fixable(self) -> bool:
        return True

    def fix(self, **kwargs) -> CheckResult:
        self._entry_path.parent.mkdir(parents=True, exist_ok=True)
        self._entry_path.write_text(ENTRY, encoding="utf-8")
        return self.detect()
```

Add to `pyproject.toml`:

```toml
tray = ["pystray>=0.19", "pillow>=10.0"]
```

Add `AutostartCheck(config)` to `build_checks()`, last.

Add a `serve` command to `cli.py` that starts the server and, if the tray is available, runs the icon in the foreground:

```python
    serve = sub.add_parser("serve", help="run the app (page + tray)")
    serve.add_argument("--port", type=int, default=7788)
    serve.add_argument("--no-tray", action="store_true")
    serve.add_argument("--no-browser", action="store_true")
```

```python
    if args.command == "serve":
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
                pass
            return 0

        run_tray(url, session=application.state.session_getter())
        return 0
```

Expose `app.state.session_getter = _session` inside `create_app` so the tray shares the server's session.

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_tray.py tests/test_doctor_autostart.py -v`
Expected: PASS — 11 passed (icon tests skip if Pillow is absent)

- [ ] **Step 5: Commit**

```bash
git add src/beyondmeetings pyproject.toml tests/test_tray.py tests/test_doctor_autostart.py
git commit -m "feat: optional tray icon, autostart entry and serve command"
```

---

## Task 8: Docs, suite and tracker

**Files:**
- Modify: `README.md`, `CONTRIBUTING.md`, `PROGRESS.md`

- [ ] **Step 1: Run the whole suite**

Run: `.venv/bin/python -m pytest -q`
Expected: PASS, zero failures

- [ ] **Step 2: Verify the app end to end**

```bash
.venv/bin/beyondmeetings serve --no-tray --no-browser --port 7799
```
Confirm: `/` serves the app page; `/setup` still serves the wizard; `/api/recording` reports idle; `/api/meetings` lists real vault notes; `/app.css` and `/app.js` load.

- [ ] **Step 3: Verify B2 is genuinely closed**

Drive `RolloverWorker` with a fake clock over a simulated three-hour meeting and assert that segments close on schedule and each is transcribed once, with earlier audio discarded.

- [ ] **Step 4: Update the docs**

`README.md`: document `beyondmeetings serve`, the app page, the optional `[tray]` extra, and that long meetings are segmented automatically. `CONTRIBUTING.md`: note the session/rollover split and that `tick()` is the tested unit, not the thread.

- [ ] **Step 5: Update `PROGRESS.md` and commit**

Tick milestone 4, mark **B2 fully closed**, note that the project is feature-complete against the spec, and list what remains before shipping.

```bash
git add README.md CONTRIBUTING.md PROGRESS.md
git commit -m "docs: milestone 4 complete"
```

---

## Self-Review

**Spec coverage:** §10 record control with live elapsed time and progress → Tasks 3, 5, 6. §10 searchable history → Tasks 4, 6. §10 re-run notes without a terminal → Tasks 5, 6. §9 B2 rollover → Tasks 1, 2, 3. §6 check 9 autostart → Task 7.

**Design decision worth stating:** the transcript is written to disk **before** the LLM is called, and a note-generation failure surfaces the transcript path plus a Regenerate button. Losing an hour of audio to an API outage would be the worst possible failure mode for this tool.

**Deliberate scope limits:** the tray is optional (`[tray]` extra); it degrades to a printed hint. There is no authentication on the local server — it binds `127.0.0.1` only, which is the same posture as the wizard.

**Existing tests that must change, not just be added:** `tests/test_server.py::test_setup_page_is_served` currently asserts `/` returns the wizard. Task 5 makes `/` the app page. The plan updates it rather than leaving a contradiction.

**Type consistency:** `SessionManager.status()` returns the dict keys consumed by `server.py` (Task 5) and `app.js` (Task 6) — `phase`, `detail`, `recording`, `name`, `elapsed_seconds`, `segments_done`, `segments_total`, `note_path`, `transcript_path`, `error`. `RolloverWorker(recorder, segment_minutes, on_segment_closed)` matches between Tasks 2 and 3. `combine_transcripts(segments, transcriber, on_progress)` matches between Tasks 1 and 3.
