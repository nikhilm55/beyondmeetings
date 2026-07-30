import pytest

from beyondmeetings.audio.pipewire import PipeWireRecorder, build_filename_base


class FakeRunner:
    """Records commands; returns canned stdout per command shape."""

    def __init__(self):
        self.commands = []
        self.next_module_id = 100

    def run(self, args) -> str:
        self.commands.append(args)
        if args[:2] == ["pactl", "load-module"]:
            self.next_module_id += 1
            return str(self.next_module_id)
        if args[:3] == ["pactl", "list", "sources"]:
            return "1\talsa_output.pci.monitor\n2\tmeeting_mix.monitor\n"
        if args[:2] == ["pactl", "info"]:
            return "Default Source: alsa_input.pci\n"
        return ""

    def spawn(self, args) -> int:
        self.commands.append(args)
        return 4242


def test_filename_base_is_slugified_with_timestamp():
    base = build_filename_base("Client Kickoff!", "2026-07-30", "14-30")
    assert base == "2026-07-30_14-30_client-kickoff"


def test_filename_base_falls_back_when_name_has_no_safe_chars():
    assert build_filename_base("!!!", "2026-07-30", "14-30") == "2026-07-30_14-30_meeting"


def test_start_creates_null_sink_first(tmp_path):
    runner = FakeRunner()
    PipeWireRecorder(data_dir=tmp_path, runner=runner).start("Standup")
    assert runner.commands[0][:3] == ["pactl", "load-module", "module-null-sink"]


def test_start_loops_monitors_excluding_the_mix_itself(tmp_path):
    runner = FakeRunner()
    PipeWireRecorder(data_dir=tmp_path, runner=runner).start("Standup")
    loopbacks = [c for c in runner.commands if "module-loopback" in c]
    sources = " ".join(" ".join(c) for c in loopbacks)
    assert "alsa_output.pci.monitor" in sources
    assert "source=meeting_mix.monitor" not in sources


def test_start_also_loops_the_default_microphone(tmp_path):
    runner = FakeRunner()
    PipeWireRecorder(data_dir=tmp_path, runner=runner).start("Standup")
    sources = " ".join(" ".join(c) for c in runner.commands)
    assert "alsa_input.pci" in sources


def test_start_records_module_ids_into_state(tmp_path):
    runner = FakeRunner()
    state = PipeWireRecorder(data_dir=tmp_path, runner=runner).start("Standup")
    assert len(state.module_ids) >= 2
    assert state.pid == 4242


def test_start_writes_first_segment_path(tmp_path):
    runner = FakeRunner()
    state = PipeWireRecorder(data_dir=tmp_path, runner=runner).start("Standup")
    assert state.segments[0].endswith("_seg000.wav")


def test_status_reflects_persisted_state(tmp_path):
    runner = FakeRunner()
    recorder = PipeWireRecorder(data_dir=tmp_path, runner=runner)
    recorder.start("Standup")
    assert recorder.status().name == "Standup"


def test_stop_unloads_every_module(tmp_path):
    runner = FakeRunner()
    recorder = PipeWireRecorder(data_dir=tmp_path, runner=runner)
    state = recorder.start("Standup")
    runner.commands.clear()
    recorder.stop()
    unloaded = [c[-1] for c in runner.commands if c[:2] == ["pactl", "unload-module"]]
    assert sorted(unloaded) == sorted(str(m) for m in state.module_ids)


def test_stop_clears_state(tmp_path):
    runner = FakeRunner()
    recorder = PipeWireRecorder(data_dir=tmp_path, runner=runner)
    recorder.start("Standup")
    recorder.stop()
    assert recorder.status() is None


def test_stop_without_start_raises(tmp_path):
    with pytest.raises(RuntimeError, match="no active recording"):
        PipeWireRecorder(data_dir=tmp_path, runner=FakeRunner()).stop()


def test_roll_segment_appends_a_new_file_and_returns_the_finished_one(tmp_path):
    runner = FakeRunner()
    recorder = PipeWireRecorder(data_dir=tmp_path, runner=runner)
    recorder.start("Standup")
    finished = recorder.roll_segment()
    state = recorder.status()
    assert finished.endswith("_seg000.wav")
    assert len(state.segments) == 2
    assert state.segments[1].endswith("_seg001.wav")


def test_stale_modules_are_cleaned_before_a_new_start(tmp_path):
    runner = FakeRunner()
    recorder = PipeWireRecorder(data_dir=tmp_path, runner=runner)
    recorder.start("First")
    runner.commands.clear()
    recorder.start("Second")
    assert any(c[:2] == ["pactl", "unload-module"] for c in runner.commands)


# --- Review finding #9: corrupt state must not wedge the app ---

def test_status_returns_none_on_corrupt_state_instead_of_raising(tmp_path):
    recorder = PipeWireRecorder(data_dir=tmp_path, runner=FakeRunner())
    (tmp_path / "recording-state.json").write_text("{ not json")
    assert recorder.status() is None
    assert "corrupt" in recorder.state_error


def test_state_error_clears_once_the_file_is_readable(tmp_path):
    recorder = PipeWireRecorder(data_dir=tmp_path, runner=FakeRunner())
    (tmp_path / "recording-state.json").write_text("{ not json")
    recorder.status()
    recorder.reset()
    assert recorder.status() is None
    assert recorder.state_error is None


def test_reset_removes_a_corrupt_state_file(tmp_path):
    recorder = PipeWireRecorder(data_dir=tmp_path, runner=FakeRunner())
    (tmp_path / "recording-state.json").write_text("{ not json")
    recorder.reset()
    assert not (tmp_path / "recording-state.json").exists()


def test_reset_tears_down_modules_of_a_live_recording(tmp_path):
    runner = FakeRunner()
    recorder = PipeWireRecorder(data_dir=tmp_path, runner=runner)
    state = recorder.start("Test")
    runner.commands.clear()
    recorder.reset()
    unloaded = [c[-1] for c in runner.commands if c[:2] == ["pactl", "unload-module"]]
    assert sorted(unloaded) == sorted(str(m) for m in state.module_ids)
    assert recorder.status() is None


def test_roll_and_stop_do_not_interleave(tmp_path):
    """roll_segment and stop are two writers of the same state file."""
    import threading

    runner = FakeRunner()
    recorder = PipeWireRecorder(data_dir=tmp_path, runner=runner)
    recorder.start("Test")

    order = []
    original = recorder._spawn_capture

    def slow_spawn(target):
        order.append("spawn-enter")
        threading.Event().wait(0.05)
        order.append("spawn-exit")
        return original(target)

    recorder._spawn_capture = slow_spawn
    roller = threading.Thread(target=recorder.roll_segment)
    roller.start()
    threading.Event().wait(0.01)
    try:
        recorder.stop()
    except RuntimeError:
        pass
    roller.join()

    # The lock must not let stop() slip between spawn-enter and spawn-exit.
    assert order == ["spawn-enter", "spawn-exit"]
