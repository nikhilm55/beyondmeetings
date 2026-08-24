from pathlib import Path

from beyondmeetings.audio.windows import WindowsRecorder


class Runner:
    def __init__(self):
        self.spawned = []
        self.killed = []

    def spawn(self, args):
        self.spawned.append(args)
        target = Path(args[-1])
        target.write_bytes(b"RIFF-fake")
        target.with_suffix(".done").touch()
        return 700 + len(self.spawned)

    def kill(self, pid):
        self.killed.append(pid)


def test_windows_records_segmented_wav_files(tmp_path):
    runner = Runner()
    recorder = WindowsRecorder(tmp_path, runner=runner)
    state = recorder.start("Planning")
    assert state.segments[0].endswith("_seg000.wav")
    assert recorder.roll_segment().endswith("_seg000.wav")
    stopped = recorder.stop()
    assert stopped.segments[-1].endswith("_seg001.wav")
    assert recorder.status() is None
    assert runner.killed == []


def test_windows_reset_clears_corrupt_state(tmp_path):
    recorder = WindowsRecorder(tmp_path, runner=Runner())
    recorder.state_path.parent.mkdir(parents=True, exist_ok=True)
    recorder.state_path.write_text("not json")
    assert recorder.status() is None
    assert recorder.state_error
    recorder.reset()
    assert recorder.state_error is None
