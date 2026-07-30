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


def test_combine_only_transcribes_the_uncached_segment(tmp_path):
    """The point of rollover: stop() should have almost nothing left to do."""
    done = [_wav(tmp_path, f"seg00{i}.wav") for i in range(3)]
    for index, audio in enumerate(done[:-1]):
        transcript_path(audio).write_text(f"part {index}")
    t = FakeTranscriber("final part")
    result = combine_transcripts(done, t)
    assert len(t.calls) == 1
    assert result == "part 0\npart 1\nfinal part"


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
