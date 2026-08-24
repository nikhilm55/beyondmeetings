"""macOS capture, driven entirely through the injected runner.

The Swift helper cannot run here, so every assertion is about the commands
MacRecorder issues. That is deliberate: the command surface is the contract
between the Python side and `bmcapture`, and it is the part that can be pinned
down without a Mac.
"""
import pytest

from beyondmeetings.audio.base import Recorder
from beyondmeetings.audio.macos import MacRecorder, resolve_helper


class FakeRunner:
    """Records commands; reports success unless told otherwise."""

    def __init__(self, mix_succeeds=True):
        self.commands = []
        self.mix_succeeds = mix_succeeds
        self._pid = 5000

    def run(self, args) -> str:
        self.commands.append(args)
        return ""

    def spawn(self, args) -> int:
        self.commands.append(args)
        self._pid += 1
        return self._pid

    def succeeded(self, args) -> bool:
        self.commands.append(args)
        return self.mix_succeeds

    # --- helpers for assertions ---

    def of(self, program):
        return [c for c in self.commands if program in c[0]]

    @property
    def flat(self):
        return [" ".join(c) for c in self.commands]


def _recorder(tmp_path, runner=None, **kw):
    return MacRecorder(
        tmp_path, runner=runner or FakeRunner(), helper="/opt/bmcapture", **kw
    )


def _capture(recorder, state, index=0):
    """Stand in for the helper actually writing its two streams.

    Without this there is nothing to mix, and MacRecorder correctly skips
    ffmpeg — calling it on files the helper never wrote would only fail.
    """
    system, mic = recorder._intermediates(state, index)
    system.parent.mkdir(parents=True, exist_ok=True)
    system.write_bytes(b"RIFF")
    mic.write_bytes(b"RIFF")
    return system, mic


# --- interface ---

def test_the_mac_backend_satisfies_the_recorder_interface(tmp_path):
    assert isinstance(_recorder(tmp_path), Recorder)


# --- start ---

def test_start_spawns_the_helper_with_both_output_paths(tmp_path):
    runner = FakeRunner()
    _recorder(tmp_path, runner).start("Client Kickoff")

    spawned = runner.of("bmcapture")[0]
    assert spawned[:2] == ["/opt/bmcapture", "record"]
    assert "--system" in spawned and "--mic" in spawned


def test_start_writes_the_two_streams_to_distinguishable_paths(tmp_path):
    runner = FakeRunner()
    _recorder(tmp_path, runner).start("Standup")

    spawned = runner.of("bmcapture")[0]
    system = spawned[spawned.index("--system") + 1]
    mic = spawned[spawned.index("--mic") + 1]
    assert system.endswith("_seg000.system.wav")
    assert mic.endswith("_seg000.mic.wav")
    assert system != mic


def test_start_records_the_final_mixed_path_not_the_intermediates(tmp_path):
    """Everything downstream consumes state.segments; it must see one file."""
    state = _recorder(tmp_path).start("Standup")

    assert len(state.segments) == 1
    assert state.segments[0].endswith("_seg000.wav")
    assert ".system." not in state.segments[0]
    assert ".mic." not in state.segments[0]


def test_start_uses_the_shared_filename_convention(tmp_path):
    state = _recorder(tmp_path).start("Client Kickoff!")

    assert state.filename_base.endswith("_client-kickoff")
    assert state.name == "Client Kickoff!"


def test_start_after_a_stale_recording_clears_it(tmp_path):
    runner = FakeRunner()
    recorder = _recorder(tmp_path, runner)
    recorder.start("First")
    recorder.start("Second")

    assert recorder.status().name == "Second"


# --- rollover ---

def test_roll_segment_stops_the_helper_then_starts_the_next(tmp_path):
    runner = FakeRunner()
    recorder = _recorder(tmp_path, runner)
    recorder.start("Long meeting")
    runner.commands.clear()

    recorder.roll_segment()

    assert runner.commands[0][0] == "kill"
    assert "bmcapture" in runner.commands[1][0]


def test_roll_segment_respawns_before_mixing(tmp_path):
    """Mixing first would extend the audio gap by however long ffmpeg takes."""
    runner = FakeRunner()
    recorder = _recorder(tmp_path, runner)
    state = recorder.start("Long meeting")
    _capture(recorder, state, 0)
    runner.commands.clear()

    recorder.roll_segment()

    programs = [c[0] for c in runner.commands]
    assert programs.index("/opt/bmcapture") < next(
        i for i, p in enumerate(programs) if "ffmpeg" in p
    ), f"ffmpeg ran before the next segment was spawned: {programs}"


def test_roll_segment_returns_the_finished_mixed_path(tmp_path):
    recorder = _recorder(tmp_path)
    recorder.start("Long meeting")

    finished = recorder.roll_segment()

    assert finished.endswith("_seg000.wav")
    assert ".system." not in finished and ".mic." not in finished


def test_roll_segment_appends_the_next_segment_to_the_state(tmp_path):
    recorder = _recorder(tmp_path)
    recorder.start("Long meeting")
    recorder.roll_segment()

    segments = recorder.status().segments
    assert len(segments) == 2
    assert segments[1].endswith("_seg001.wav")


# --- mixing ---

def test_the_mix_combines_both_streams_into_one_file(tmp_path):
    runner = FakeRunner()
    recorder = _recorder(tmp_path, runner)
    state = recorder.start("Standup")
    _capture(recorder, state, 0)
    recorder.stop()

    mix = next(c for c in runner.commands if "ffmpeg" in c[0])
    assert mix.count("-i") == 2, f"expected two inputs: {mix}"
    assert any("amix=inputs=2" in part for part in mix)


def test_the_mix_does_not_force_a_format(tmp_path):
    """compress_for_upload already makes it mono 16k; doing it twice loses quality."""
    runner = FakeRunner()
    recorder = _recorder(tmp_path, runner)
    state = recorder.start("Standup")
    _capture(recorder, state, 0)
    recorder.stop()

    mix = next(c for c in runner.commands if "ffmpeg" in c[0])
    assert "-ar" not in mix and "-ac" not in mix


def test_successful_mix_deletes_the_intermediates(tmp_path):
    runner = FakeRunner(mix_succeeds=True)
    recorder = _recorder(tmp_path, runner)
    state = recorder.start("Standup")
    system, mic = recorder._intermediates(state, 0)
    system.parent.mkdir(parents=True, exist_ok=True)
    system.write_bytes(b"RIFF")
    mic.write_bytes(b"RIFF")

    recorder.stop()

    assert not system.exists() and not mic.exists()


def test_a_failed_mix_keeps_the_intermediates(tmp_path):
    """They are the only copy of the meeting. Losing them to a mix failure is fatal."""
    runner = FakeRunner(mix_succeeds=False)
    recorder = _recorder(tmp_path, runner)
    state = recorder.start("Standup")
    system, mic = recorder._intermediates(state, 0)
    system.parent.mkdir(parents=True, exist_ok=True)
    system.write_bytes(b"RIFF")
    mic.write_bytes(b"RIFF")

    recorder.stop()

    assert system.exists() and mic.exists()


def test_a_missing_mic_stream_still_produces_a_segment(tmp_path):
    """No microphone, or a denied permission, must not lose the system audio."""
    runner = FakeRunner()
    recorder = _recorder(tmp_path, runner)
    state = recorder.start("Standup")
    system, _ = recorder._intermediates(state, 0)
    system.parent.mkdir(parents=True, exist_ok=True)
    system.write_bytes(b"RIFF")

    recorder.stop()

    final = tmp_path / "recordings" / state.date / f"{state.filename_base}_seg000.wav"
    assert final.exists(), "system-only audio was dropped instead of kept"


# --- stop ---

def test_stop_kills_the_helper(tmp_path):
    runner = FakeRunner()
    recorder = _recorder(tmp_path, runner)
    recorder.start("Standup")
    runner.commands.clear()

    recorder.stop()

    assert runner.commands[0][0] == "kill"


def test_stop_without_a_recording_is_an_error(tmp_path):
    with pytest.raises(RuntimeError, match="no active recording"):
        _recorder(tmp_path).stop()


def test_stop_clears_the_state(tmp_path):
    recorder = _recorder(tmp_path)
    recorder.start("Standup")
    recorder.stop()

    assert recorder.status() is None


# --- status, reset, state_error ---

def test_status_is_none_before_anything_starts(tmp_path):
    assert _recorder(tmp_path).status() is None


def test_a_corrupt_state_file_reports_an_error_rather_than_raising(tmp_path):
    """Raising here used to 500 every poll and wedge the UI."""
    recorder = _recorder(tmp_path)
    recorder.state_path.parent.mkdir(parents=True, exist_ok=True)
    recorder.state_path.write_text("{not json", encoding="utf-8")

    assert recorder.status() is None
    assert "corrupt" in recorder.state_error


def test_reset_forgets_a_wedged_recording(tmp_path):
    recorder = _recorder(tmp_path)
    recorder.start("Standup")

    recorder.reset()

    assert recorder.status() is None


def test_reset_survives_a_corrupt_state_file(tmp_path):
    recorder = _recorder(tmp_path)
    recorder.state_path.parent.mkdir(parents=True, exist_ok=True)
    recorder.state_path.write_text("{not json", encoding="utf-8")

    recorder.reset()

    assert recorder.status() is None
    assert recorder.state_error is None


# --- helper resolution ---

def test_the_helper_is_found_inside_the_app_bundle(tmp_path):
    bundle = tmp_path / "Applications" / "beyondMeetings.app" / "Contents" / "MacOS"
    bundle.mkdir(parents=True)
    helper = bundle / "bmcapture"
    helper.write_text("", encoding="utf-8")
    helper.chmod(0o755)

    assert resolve_helper(home=tmp_path) == str(helper)


def test_an_explicit_override_wins(tmp_path, monkeypatch):
    monkeypatch.setenv("BEYONDMEETINGS_CAPTURE_HELPER", "/custom/bmcapture")
    assert resolve_helper(home=tmp_path) == "/custom/bmcapture"


def test_it_falls_back_to_the_bare_name_on_path(tmp_path):
    assert resolve_helper(home=tmp_path) == "bmcapture"
