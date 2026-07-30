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

        # A transcription failure must not end segmentation for the rest of the
        # meeting — the segment's audio stays on disk and stop() retries it.
        try:
            self.on_segment_closed(finished)
        except Exception:
            log.exception("background transcription failed for %s", finished)
