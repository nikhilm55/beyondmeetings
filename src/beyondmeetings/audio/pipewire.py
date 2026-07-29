"""Linux capture via a PipeWire null sink.

Every sink monitor plus the default microphone is looped into one mixing bus,
so no participant is missed regardless of which output device the call app
uses. Long meetings roll over into fresh segments so each can be transcribed
while the next records — this is what keeps a multi-hour meeting under Groq's
hourly audio-seconds cap.
"""
from __future__ import annotations

import re
import subprocess
from datetime import datetime
from pathlib import Path

from .base import Recorder, RecordingState, clear_state, load_state, save_state

MIX_SINK = "meeting_mix"


class SubprocessRunner:
    def run(self, args: list[str]) -> str:
        return subprocess.run(
            args, capture_output=True, text=True, check=False
        ).stdout.strip()

    def spawn(self, args: list[str]) -> int:
        return subprocess.Popen(args).pid


def build_filename_base(name: str, day: str, clock: str) -> str:
    slug = re.sub(r"[^a-z0-9-]", "", name.lower().replace(" ", "-")).strip("-")
    return f"{day}_{clock}_{slug or 'meeting'}"


class PipeWireRecorder(Recorder):
    def __init__(self, data_dir: Path, runner=None, segment_minutes: int = 50):
        self.data_dir = Path(data_dir)
        self.runner = runner or SubprocessRunner()
        self.segment_minutes = segment_minutes
        self.state_path = self.data_dir / "recording-state.json"

    # ---------- helpers ----------

    def _segment_path(self, state: RecordingState, index: int) -> Path:
        folder = self.data_dir / "recordings" / state.date
        folder.mkdir(parents=True, exist_ok=True)
        return folder / f"{state.filename_base}_seg{index:03d}.wav"

    def _spawn_capture(self, target: Path) -> int:
        return self.runner.spawn(
            ["pw-record", "--target", f"{MIX_SINK}.monitor", str(target)]
        )

    def _teardown_modules(self, module_ids: list[int]) -> None:
        for module_id in reversed(module_ids):
            self.runner.run(["pactl", "unload-module", str(module_id)])

    # ---------- Recorder ----------

    def start(self, name: str) -> RecordingState:
        stale = load_state(self.state_path)
        if stale:
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
        state.pid = self._spawn_capture(first)

        save_state(state, self.state_path)
        return state

    def roll_segment(self) -> str:
        """End the current segment, start the next. Returns the finished path."""
        state = self.status()
        if not state:
            raise RuntimeError("no active recording")

        self.runner.run(["kill", str(state.pid)])
        finished = state.segments[-1]

        nxt = self._segment_path(state, len(state.segments))
        state.segments.append(str(nxt))
        state.pid = self._spawn_capture(nxt)
        save_state(state, self.state_path)
        return finished

    def stop(self) -> RecordingState:
        state = self.status()
        if not state:
            raise RuntimeError("no active recording")

        self.runner.run(["kill", str(state.pid)])
        self._teardown_modules(state.module_ids)
        clear_state(self.state_path)
        return state

    def status(self) -> RecordingState | None:
        return load_state(self.state_path)
