"""Linux capture via a PipeWire null sink.

Every sink monitor plus the default microphone is looped into one mixing bus,
so no participant is missed regardless of which output device the call app
uses. Long meetings roll over into fresh segments so each can be transcribed
while the next records — this is what keeps a multi-hour meeting under Groq's
hourly audio-seconds cap.
"""
from __future__ import annotations

import os
import re
import shutil
import subprocess
import threading
import time
from datetime import datetime
from pathlib import Path

from .base import (
    Recorder,
    RecordingState,
    build_filename_base,
    clear_state,
    load_state,
    save_state,
)

MIX_SINK = "meeting_mix"
MIN_WAV_BYTES = 44
CAPTURE_START_TIMEOUT = 3.0
CAPTURE_STOP_TIMEOUT = 5.0


class SubprocessRunner:
    def __init__(self):
        self._children: dict[int, subprocess.Popen] = {}

    def run(self, args: list[str]) -> str:
        return subprocess.run(
            args, capture_output=True, text=True, check=False
        ).stdout.strip()

    def spawn(self, args: list[str]) -> int:
        process = subprocess.Popen(args)
        self._children[process.pid] = process
        return process.pid

    def is_running(self, pid: int) -> bool:
        child = self._children.get(pid)
        if child is not None:
            return child.poll() is None
        try:
            os.kill(pid, 0)
        except OSError:
            return False
        return True


class PipeWireRecorder(Recorder):
    def __init__(self, data_dir: Path, runner=None, segment_minutes: int = 50):
        self.data_dir = Path(data_dir)
        self.runner = runner or SubprocessRunner()
        self.segment_minutes = segment_minutes
        self.state_path = self.data_dir / "recording-state.json"
        # The state file — not any Python field — is what decides whether a
        # recording exists. roll_segment and stop are two writers, so the
        # recorder owns the lock rather than the caller.
        self._lock = threading.RLock()

    # ---------- helpers ----------

    def _segment_path(self, state: RecordingState, index: int) -> Path:
        folder = self.data_dir / "recordings" / state.date
        folder.mkdir(parents=True, exist_ok=True)
        return folder / f"{state.filename_base}_seg{index:03d}.wav"

    def _spawn_capture(self, target: Path) -> int:
        if shutil.which("parec"):
            command = [
                "parec",
                f"--device={MIX_SINK}.monitor",
                "--file-format=wav",
                str(target),
            ]
        elif shutil.which("pw-record"):
            # Native PipeWire installations may not ship PulseAudio's parec.
            # The monitor created through pipewire-pulse is exposed as the
            # same stable node name to pw-record.
            command = [
                "pw-record",
                "--target",
                f"{MIX_SINK}.monitor",
                str(target),
            ]
        else:
            raise RuntimeError("neither parec nor pw-record is installed")
        return self.runner.spawn(command)

    def _capture_is_running(self, pid: int) -> bool:
        check = getattr(self.runner, "is_running", None)
        return check(pid) if check else True

    def _wait_for_capture(self, target: Path, pid: int) -> None:
        """Fail Start immediately if the recorder exits without a WAV."""
        deadline = time.monotonic() + CAPTURE_START_TIMEOUT
        while time.monotonic() < deadline:
            if target.is_file() and target.stat().st_size >= MIN_WAV_BYTES:
                return
            if not self._capture_is_running(pid):
                raise RuntimeError(
                    "audio capture exited before writing a WAV; check server.log"
                )
            time.sleep(0.05)
        raise RuntimeError("audio capture did not create a WAV within 3 seconds")

    def _stop_capture(self, target: Path, pid: int) -> None:
        self.runner.run(["kill", str(pid)])
        deadline = time.monotonic() + CAPTURE_STOP_TIMEOUT
        while self._capture_is_running(pid) and time.monotonic() < deadline:
            time.sleep(0.05)
        if self._capture_is_running(pid):
            self.runner.run(["kill", "-KILL", str(pid)])
        if not target.is_file() or target.stat().st_size < MIN_WAV_BYTES:
            raise RuntimeError(f"audio capture produced no usable WAV at {target}")

    def _teardown_modules(self, module_ids: list[int]) -> None:
        for module_id in reversed(module_ids):
            self.runner.run(["pactl", "unload-module", str(module_id)])

    # ---------- Recorder ----------

    def start(self, name: str) -> RecordingState:
        with self._lock:
            stale = load_state(self.state_path)
            if stale:
                try:
                    self._stop_capture(Path(stale.segments[-1]), stale.pid)
                finally:
                    self._teardown_modules(stale.module_ids)
                    clear_state(self.state_path)

            now = datetime.now()
            day = now.strftime("%Y-%m-%d")
            base = build_filename_base(name, day, now.strftime("%H-%M"))

            module_ids: list[int] = []
            null_sink = self.runner.run(
                ["pactl", "load-module", "module-null-sink",
                 f"sink_name={MIX_SINK}",
                 "sink_properties=device.description=MeetingMix"]
            )
            module_ids.append(int(null_sink))

            listing = self.runner.run(["pactl", "list", "sources", "short"])
            for line in listing.splitlines():
                parts = line.split()
                if len(parts) < 2:
                    continue
                source = parts[1]
                if not source.endswith(".monitor") or source.startswith(MIX_SINK):
                    continue
                module_ids.append(int(self.runner.run(
                    ["pactl", "load-module", "module-loopback",
                     f"source={source}", f"sink={MIX_SINK}"]
                )))

            info = self.runner.run(["pactl", "info"])
            match = re.search(r"^Default Source: (.+)$", info, re.MULTILINE)
            if match:
                module_ids.append(int(self.runner.run(
                    ["pactl", "load-module", "module-loopback",
                     f"source={match.group(1).strip()}", f"sink={MIX_SINK}"]
                )))

            state = RecordingState(
                name=name, filename_base=base, date=day, pid=0,
                module_ids=module_ids, segments=[],
                started_at=now.isoformat(timespec="seconds"),
            )
            first = self._segment_path(state, 0)
            state.segments.append(str(first))
            try:
                state.pid = self._spawn_capture(first)
                self._wait_for_capture(first, state.pid)
            except Exception:
                if state.pid:
                    self.runner.run(["kill", str(state.pid)])
                self._teardown_modules(module_ids)
                first.unlink(missing_ok=True)
                raise

            save_state(state, self.state_path)
            return state

    def roll_segment(self) -> str:
        """End the current segment, start the next. Returns the finished path."""
        with self._lock:
            state = self.status()
            if not state:
                raise RuntimeError("no active recording")

            finished = Path(state.segments[-1])
            self._stop_capture(finished, state.pid)

            nxt = self._segment_path(state, len(state.segments))
            next_pid = self._spawn_capture(nxt)
            self._wait_for_capture(nxt, next_pid)
            state.segments.append(str(nxt))
            state.pid = next_pid
            save_state(state, self.state_path)
            return str(finished)

    def stop(self) -> RecordingState:
        with self._lock:
            state = self.status()
            if not state:
                raise RuntimeError("no active recording")

            try:
                self._stop_capture(Path(state.segments[-1]), state.pid)
            finally:
                self._teardown_modules(state.module_ids)
                clear_state(self.state_path)
            return state

    def status(self) -> RecordingState | None:
        """None when not recording — and also when the state file is corrupt.

        Raising here used to make every poll 500 and left the app with no way
        back: the UI could neither start nor stop. An unreadable state file is
        reported through `state_error` and cleared by `reset()`.
        """
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
        return getattr(self, "_state_error", None)

    def reset(self) -> None:
        """Forget a wedged recording. The UI's escape hatch."""
        with self._lock:
            try:
                stale = load_state(self.state_path)
            except ValueError:
                stale = None
            if stale:
                self._teardown_modules(stale.module_ids)
                self.runner.run(["kill", str(stale.pid)])
            clear_state(self.state_path)
            self._state_error = None
