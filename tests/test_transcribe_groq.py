import pytest

from beyondmeetings.transcribe.groq import GroqTranscriber, resolve_ffmpeg


def test_resolve_ffmpeg_finds_binary_on_path(monkeypatch):
    monkeypatch.setattr("shutil.which", lambda name: "/usr/bin/ffmpeg")
    assert resolve_ffmpeg() == "/usr/bin/ffmpeg"


def test_resolve_ffmpeg_raises_with_actionable_message(monkeypatch):
    monkeypatch.setattr("shutil.which", lambda name: None)
    with pytest.raises(FileNotFoundError, match="ffmpeg"):
        resolve_ffmpeg()


def test_language_omitted_when_auto(httpx_mock, tmp_path):
    httpx_mock.add_response(text="hello world")
    audio = tmp_path / "a.mp3"
    audio.write_bytes(b"fake")
    GroqTranscriber(api_key="gsk", language="auto").transcribe_file(audio)
    body = httpx_mock.get_requests()[0].content
    assert b'name="language"' not in body


def test_language_sent_when_explicit(httpx_mock, tmp_path):
    httpx_mock.add_response(text="hello world")
    audio = tmp_path / "a.mp3"
    audio.write_bytes(b"fake")
    GroqTranscriber(api_key="gsk", language="hi").transcribe_file(audio)
    assert b'name="language"' in httpx_mock.get_requests()[0].content


def test_returns_transcript_text(httpx_mock, tmp_path):
    httpx_mock.add_response(text="the transcript")
    audio = tmp_path / "a.mp3"
    audio.write_bytes(b"fake")
    assert GroqTranscriber(api_key="gsk").transcribe_file(audio) == "the transcript"


def test_falls_back_to_second_model_on_failure(httpx_mock, tmp_path):
    httpx_mock.add_response(status_code=500, text="boom")
    httpx_mock.add_response(text="recovered")
    audio = tmp_path / "a.mp3"
    audio.write_bytes(b"fake")
    result = GroqTranscriber(api_key="gsk", max_attempts=1,
                             backoff_base=0).transcribe_file(audio)
    assert result == "recovered"


def test_rate_limit_waits_then_retries(httpx_mock, tmp_path, monkeypatch):
    slept = []
    monkeypatch.setattr("time.sleep", slept.append)
    httpx_mock.add_response(status_code=429, headers={"retry-after": "7"}, text="slow")
    httpx_mock.add_response(text="ok")
    audio = tmp_path / "a.mp3"
    audio.write_bytes(b"fake")
    assert GroqTranscriber(api_key="gsk").transcribe_file(audio) == "ok"
    assert 7 in slept


def test_raises_after_all_models_exhausted(httpx_mock, tmp_path):
    for _ in range(4):
        httpx_mock.add_response(status_code=500, text="boom")
    audio = tmp_path / "a.mp3"
    audio.write_bytes(b"fake")
    with pytest.raises(RuntimeError, match="transcription failed"):
        GroqTranscriber(api_key="gsk", max_attempts=2,
                        backoff_base=0).transcribe_file(audio)
