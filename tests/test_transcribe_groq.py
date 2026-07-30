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


# --- Review finding #1: the app path uploaded raw WAV to Groq ---

def test_wav_is_compressed_before_upload(httpx_mock, tmp_path, monkeypatch):
    """A 50-minute WAV is ~1.15GB against a 25MB cap. Compression must not be
    something a caller can forget — it belongs inside the transcriber."""
    compressed = []

    def fake_compress(source, dest):
        compressed.append((source, dest))
        dest.write_bytes(b"ID3-small")
        return dest

    monkeypatch.setattr(
        "beyondmeetings.transcribe.groq.compress_for_upload", fake_compress
    )
    httpx_mock.add_response(text="transcribed")
    wav = tmp_path / "seg000.wav"
    wav.write_bytes(b"RIFF" * 10000)

    assert GroqTranscriber(api_key="gsk").transcribe_file(wav) == "transcribed"
    assert compressed, "WAV must be compressed before upload"
    assert compressed[0][0] == wav
    assert httpx_mock.get_requests()[0].content.count(b"RIFF") == 0


def test_compressed_temp_file_is_cleaned_up(httpx_mock, tmp_path, monkeypatch):
    monkeypatch.setattr(
        "beyondmeetings.transcribe.groq.compress_for_upload",
        lambda s, d: (d.write_bytes(b"ID3"), d)[1],
    )
    httpx_mock.add_response(text="ok")
    wav = tmp_path / "seg000.wav"
    wav.write_bytes(b"RIFF")
    GroqTranscriber(api_key="gsk").transcribe_file(wav)
    assert not list(tmp_path.glob("*.mp3")), "temp mp3 must not be left behind"


def test_already_compressed_audio_is_uploaded_directly(httpx_mock, tmp_path,
                                                       monkeypatch):
    def explode(source, dest):
        raise AssertionError("must not re-compress an mp3")

    monkeypatch.setattr(
        "beyondmeetings.transcribe.groq.compress_for_upload", explode
    )
    httpx_mock.add_response(text="ok")
    mp3 = tmp_path / "a.mp3"
    mp3.write_bytes(b"ID3")
    assert GroqTranscriber(api_key="gsk").transcribe_file(mp3) == "ok"


def test_retry_after_with_a_unit_suffix_does_not_crash(httpx_mock, tmp_path,
                                                       monkeypatch):
    """Groq sends values like '7.66s'; float() raises on those."""
    slept = []
    monkeypatch.setattr("time.sleep", slept.append)
    httpx_mock.add_response(status_code=429, headers={"retry-after": "7.66s"},
                            text="slow")
    httpx_mock.add_response(text="ok")
    mp3 = tmp_path / "a.mp3"
    mp3.write_bytes(b"ID3")
    assert GroqTranscriber(api_key="gsk").transcribe_file(mp3) == "ok"
    assert slept and slept[0] == pytest.approx(7.66)


def test_retry_after_that_is_not_a_number_falls_back(httpx_mock, tmp_path,
                                                     monkeypatch):
    slept = []
    monkeypatch.setattr("time.sleep", slept.append)
    httpx_mock.add_response(status_code=429,
                            headers={"retry-after": "Wed, 21 Oct 2026 07:28:00 GMT"},
                            text="slow")
    httpx_mock.add_response(text="ok")
    mp3 = tmp_path / "a.mp3"
    mp3.write_bytes(b"ID3")
    assert GroqTranscriber(api_key="gsk").transcribe_file(mp3) == "ok"
    assert slept and slept[0] > 0
