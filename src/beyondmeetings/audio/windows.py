"""Windows recording through WASAPI loopback and the default microphone."""
from __future__ import annotations

import subprocess
import sys
import threading
import time
from datetime import datetime
from pathlib import Path

from .base import (
    Recorder, RecordingState, build_filename_base, clear_state, load_state, save_state,
)


class SubprocessRunner:
    def spawn(self, args: list[str]) -> int:
        flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        return subprocess.Popen(
            args, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL, creationflags=flags,
        ).pid

    def kill(self, pid: int) -> None:
        subprocess.run(
            ["taskkill", "/PID", str(pid), "/T", "/F"],
            capture_output=True, check=False,
        )


class WindowsRecorder(Recorder):
    """Segmented recorder whose worker keeps WAV headers valid on shutdown."""

    def __init__(self, data_dir: Path, runner=None, segment_minutes: int = 50):
        self.data_dir = Path(data_dir)
        self.runner = runner or SubprocessRunner()
        self.segment_minutes = segment_minutes
        self.state_path = self.data_dir / "recording-state.json"
        self._lock = threading.RLock()
        self._state_error: str | None = None

    def _segment_path(self, state: RecordingState, index: int) -> Path:
        folder = self.data_dir / "recordings" / state.date
        folder.mkdir(parents=True, exist_ok=True)
        return folder / f"{state.filename_base}_seg{index:03d}.wav"

    @staticmethod
    def _signal_paths(target: Path) -> tuple[Path, Path, Path]:
        return (
            target.with_suffix(".stop"),
            target.with_suffix(".done"),
            target.with_suffix(".error"),
        )

    def _spawn(self, target: Path) -> int:
        stop, done, error = self._signal_paths(target)
        stop.unlink(missing_ok=True)
        done.unlink(missing_ok=True)
        error.unlink(missing_ok=True)
        return self.runner.spawn([
            sys.executable, "-m", "beyondmeetings.audio.windows_worker", str(target)
        ])

    def _finish(self, target: Path, pid: int, timeout: float = 12.0) -> None:
        stop, done, error = self._signal_paths(target)
        stop.touch()
        deadline = time.monotonic() + timeout
        while not done.exists() and time.monotonic() < deadline:
            time.sleep(0.05)
        if not done.exists():
            self.runner.kill(pid)
            raise RuntimeError("Windows audio capture did not stop cleanly")
        stop.unlink(missing_ok=True)
        done.unlink(missing_ok=True)
        if error.exists():
            detail = error.read_text(encoding="utf-8", errors="replace")
            error.unlink(missing_ok=True)
            raise RuntimeError(f"Windows audio capture failed: {detail}")

    def start(self, name: str) -> RecordingState:
        with self._lock:
            stale = self.status()
            if stale:
                self._finish(Path(stale.segments[-1]), stale.pid)
                clear_state(self.state_path)
            now = datetime.now()
            day = now.strftime("%Y-%m-%d")
            state = RecordingState(
                name=name,
                filename_base=build_filename_base(name, day, now.strftime("%H-%M")),
                date=day, pid=0, segments=[], started_at=now.isoformat(timespec="seconds"),
            )
            target = self._segment_path(state, 0)
            state.segments.append(str(target))
            state.pid = self._spawn(target)
            save_state(state, self.state_path)
            return state

    def roll_segment(self) -> str:
        with self._lock:
            state = self.status()
            if not state:
                raise RuntimeError("no active recording")
            finished = Path(state.segments[-1])
            self._finish(finished, state.pid)
            target = self._segment_path(state, len(state.segments))
            state.segments.append(str(target))
            state.pid = self._spawn(target)
            save_state(state, self.state_path)
            return str(finished)

    def stop(self) -> RecordingState:
        with self._lock:
            state = self.status()
            if not state:
                raise RuntimeError("no active recording")
            self._finish(Path(state.segments[-1]), state.pid)
            clear_state(self.state_path)
            return state

    def status(self) -> RecordingState | None:
        with self._lock:
            try:
                state = load_state(self.state_path)
            except ValueError as exc:
                self._state_error = str(exc)
                return None
            self._state_error = None
            return state

    @property
    def state_error(self) -> str | None:
        return self._state_error

    def reset(self) -> None:
        with self._lock:
            try:
                stale = load_state(self.state_path)
            except ValueError:
                stale = None
            if stale:
                try:
                    self._finish(Path(stale.segments[-1]), stale.pid)
                except RuntimeError:
                    pass
            clear_state(self.state_path)
            self._state_error = None
