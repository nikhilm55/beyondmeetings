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
        self._n = 0

    def start(self, name):
        self._n += 1
        seg = self.tmp_path / f"seg{self._n:03d}.wav"
        seg.write_bytes(b"RIFF")
        self.state = RecordingState(
            name=name, filename_base=f"2026-07-30_10-00_test{self._n}",
            date="2026-07-30", pid=1, module_ids=[1], segments=[str(seg)],
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


def _build(tmp_path, provider):
    vault = tmp_path / "vault"
    vault.mkdir(exist_ok=True)
    scaffold_vault(vault)
    data = tmp_path / "data"
    data.mkdir(exist_ok=True)
    return SessionManager(
        config=Config(vault_path=str(vault), data_dir=str(data)),
        recorder=FakeRecorder(tmp_path),
        transcriber_factory=lambda c: FakeTranscriber(),
        provider_factory=lambda c: provider,
    )


@pytest.fixture
def manager(tmp_path):
    return _build(tmp_path, FakeProvider(_note()))


@pytest.fixture
def failing(tmp_path):
    return _build(tmp_path, FakeProvider(error=RuntimeError("api down")))


def test_starts_idle(manager):
    assert manager.status()["phase"] == "idle"
    assert manager.status()["recording"] is False


def test_start_reports_recording(manager):
    manager.start("Test Meeting")
    status = manager.status()
    assert status["phase"] == "recording"
    assert status["recording"] is True
    assert status["name"] == "Test Meeting"


def test_start_without_a_name_uses_a_timestamp_placeholder(manager):
    manager.start("")
    assert manager.status()["name"].startswith("recording-")


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
    assert seen[-1] == "done"


def test_a_failing_provider_surfaces_the_error_not_a_crash(failing):
    failing.start("Test")
    failing.run_stop()
    status = failing.status()
    assert status["phase"] == "failed"
    assert "api down" in status["error"]


def test_the_transcript_survives_a_provider_failure(failing, tmp_path):
    """Losing an hour of audio to a note-generation error is unacceptable."""
    failing.start("Test")
    failing.run_stop()
    assert list((tmp_path / "data" / "transcripts").rglob("*.txt"))
    assert failing.status()["transcript_path"]


def test_the_failure_message_points_at_the_saved_transcript(failing):
    failing.start("Test")
    failing.run_stop()
    assert "Regenerate" in failing.status()["error"]


def test_can_start_again_after_a_completed_meeting(manager):
    manager.start("First")
    manager.run_stop()
    manager.start("Second")
    assert manager.status()["name"] == "Second"


def test_can_start_again_after_a_failed_stop(failing):
    failing.start("First")
    failing.run_stop()
    failing.start("Second")
    assert failing.status()["recording"] is True


def test_starting_again_clears_the_previous_error(failing):
    failing.start("First")
    failing.run_stop()
    failing.start("Second")
    assert failing.status()["error"] is None


# --- Review findings #2, #8, #9, #12 ---

def test_concurrent_starts_only_one_wins(manager):
    """FastAPI runs sync endpoints in a threadpool: two tabs really can race."""
    import threading

    barrier = threading.Barrier(4)
    accepted, rejected = [], []

    def attempt():
        barrier.wait()
        try:
            manager.start("Race")
            accepted.append(1)
        except RuntimeError:
            rejected.append(1)

    threads = [threading.Thread(target=attempt) for _ in range(4)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert len(accepted) == 1, "exactly one start must win"
    assert len(rejected) == 3


def test_run_stop_joins_the_ticker_before_tearing_down(manager):
    """A roll_segment landing after teardown re-creates the state file and
    wedges the app permanently."""
    joined = []
    manager.start("Test")
    real = manager._ticker

    class Watcher:
        def is_alive(self):
            return True

        def join(self, timeout=None):
            joined.append(timeout)

    manager._ticker = Watcher()
    manager.run_stop()
    manager._ticker = real
    assert joined, "run_stop must join the ticker before recorder.stop()"


def test_status_reports_a_rollover_failure(manager):
    manager.start("Test")
    with manager._lock:
        manager._rollover_error = "Segmentation stopped: boom"
    assert "Segmentation stopped" in manager.status()["rollover_error"]


def test_status_exposes_a_recorder_state_error(manager):
    class Wedged:
        state_error = "corrupt recording state"

        def status(self):
            return None

    manager.recorder = Wedged()
    assert manager.status()["state_error"] == "corrupt recording state"


def test_reset_clears_a_wedged_session(manager):
    reset_called = []

    class Wedged:
        state_error = "corrupt"

        def status(self):
            return None

        def reset(self):
            reset_called.append(1)

    manager.recorder = Wedged()
    status = manager.reset()
    assert reset_called == [1]
    assert status["phase"] == "idle"
    assert status["error"] is None
