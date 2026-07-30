import pytest

from beyondmeetings.config import Config
from beyondmeetings.doctor.transcriber import WhisperModelCheck
from beyondmeetings.transcribe.factory import build_transcriber
from beyondmeetings.transcribe.groq import GroqTranscriber
from beyondmeetings.transcribe.whispercpp import WhisperCppTranscriber


def test_builds_groq_by_default(monkeypatch):
    monkeypatch.setattr(
        "beyondmeetings.transcribe.factory.get_secret", lambda *a, **k: "gsk"
    )
    assert isinstance(build_transcriber(Config()), GroqTranscriber)


def test_groq_without_a_key_raises_actionably(monkeypatch):
    monkeypatch.setattr(
        "beyondmeetings.transcribe.factory.get_secret", lambda *a, **k: None
    )
    with pytest.raises(RuntimeError, match="beyondmeetings setup"):
        build_transcriber(Config(transcriber="groq"))


def test_builds_whispercpp_when_configured(tmp_path):
    binary = tmp_path / "whisper-cli"
    binary.write_text("")
    binary.chmod(0o755)
    cfg = Config(transcriber="whispercpp", whisper_binary=str(binary))
    built = build_transcriber(cfg)
    assert isinstance(built, WhisperCppTranscriber)
    assert built.binary == str(binary)


def test_unknown_transcriber_raises():
    with pytest.raises(ValueError, match="unknown transcriber"):
        build_transcriber(Config(transcriber="nope"))


def test_spoken_language_is_passed_through(monkeypatch):
    monkeypatch.setattr(
        "beyondmeetings.transcribe.factory.get_secret", lambda *a, **k: "gsk"
    )
    assert build_transcriber(Config(spoken_language="hi")).language == "hi"


def test_model_check_is_skipped_when_using_groq():
    check = WhisperModelCheck(Config(transcriber="groq"))
    assert check.detect().status == "ok"
    assert check.required is False


def test_model_check_missing_when_model_absent(tmp_path, monkeypatch):
    monkeypatch.setattr("pathlib.Path.home", lambda: tmp_path)
    check = WhisperModelCheck(Config(transcriber="whispercpp"))
    assert check.detect().status == "missing"


def test_model_check_ok_when_model_present(tmp_path, monkeypatch):
    monkeypatch.setattr("pathlib.Path.home", lambda: tmp_path)
    models = tmp_path / ".local" / "share" / "beyondmeetings" / "models"
    models.mkdir(parents=True)
    (models / "ggml-medium.en.bin").write_bytes(b"x" * 10)
    assert WhisperModelCheck(Config(transcriber="whispercpp")).detect().status == "ok"


def test_model_check_not_fixable_when_using_groq():
    assert WhisperModelCheck(Config(transcriber="groq")).fixable is False
