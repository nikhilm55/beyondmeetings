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
        path = f"/data/seg{self._counter:03d}.wav"
        self._counter += 1
        self.rolled.append(self._counter)
        return path


def _worker(recorder, closed, minutes=50):
    return RolloverWorker(
        recorder=recorder, segment_minutes=minutes, on_segment_closed=closed.append
    )


START = datetime(2026, 7, 30, 10, 0, 0)


def test_does_not_roll_before_the_interval():
    recorder = FakeRecorder()
    worker = _worker(recorder, [])
    worker.mark_segment_start(START)
    worker.tick(START + timedelta(minutes=49))
    assert recorder.rolled == []


def test_rolls_once_the_interval_elapses():
    recorder = FakeRecorder()
    worker = _worker(recorder, [])
    worker.mark_segment_start(START)
    worker.tick(START + timedelta(minutes=50))
    assert recorder.rolled == [1]


def test_hands_the_finished_segment_to_the_callback():
    recorder = FakeRecorder()
    closed = []
    worker = _worker(recorder, closed)
    worker.mark_segment_start(START)
    worker.tick(START + timedelta(minutes=50))
    assert closed == ["/data/seg000.wav"]


def test_rolls_repeatedly_across_a_long_meeting():
    recorder = FakeRecorder()
    worker = _worker(recorder, [])
    now = START
    worker.mark_segment_start(now)
    for _ in range(5):
        now += timedelta(minutes=50)
        worker.tick(now)
    assert recorder.rolled == [1, 2, 3, 4, 5]


def test_timer_resets_after_each_roll():
    recorder = FakeRecorder()
    worker = _worker(recorder, [])
    worker.mark_segment_start(START)
    worker.tick(START + timedelta(minutes=50))
    worker.tick(START + timedelta(minutes=99))
    assert recorder.rolled == [1]
    worker.tick(START + timedelta(minutes=100))
    assert recorder.rolled == [1, 2]


def test_does_nothing_when_not_recording():
    recorder = FakeRecorder(active=False)
    worker = _worker(recorder, [])
    worker.mark_segment_start(START)
    worker.tick(START + timedelta(minutes=90))
    assert recorder.rolled == []


def test_tick_before_any_start_is_a_no_op():
    recorder = FakeRecorder()
    _worker(recorder, []).tick(START)
    assert recorder.rolled == []


def test_a_failing_callback_does_not_stop_future_rolls():
    """A transcription failure mid-meeting must not end segmentation."""
    recorder = FakeRecorder()

    def explode(_):
        raise RuntimeError("groq down")

    worker = RolloverWorker(
        recorder=recorder, segment_minutes=50, on_segment_closed=explode
    )
    worker.mark_segment_start(START)
    worker.tick(START + timedelta(minutes=50))
    worker.tick(START + timedelta(minutes=100))
    assert recorder.rolled == [1, 2]


def test_a_three_hour_meeting_produces_the_expected_segment_count():
    """B2 regression: this is the shape of the 2026-07-08 failure."""
    recorder = FakeRecorder()
    closed = []
    worker = _worker(recorder, closed)
    worker.mark_segment_start(START)
    for minute in range(1, 181):
        worker.tick(START + timedelta(minutes=minute))
    assert len(closed) == 3
    assert len(set(closed)) == 3
