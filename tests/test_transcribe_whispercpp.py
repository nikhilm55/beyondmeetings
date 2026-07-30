import pytest

from beyondmeetings.transcribe.whispercpp import (
    MODEL_URL, WhisperCppTranscriber, resolve_whisper_binary,
)


def _executable(path):
    path.write_text("#!/bin/sh\n")
    path.chmod(0o755)
    return path


def test_prefers_an_explicitly_configured_binary(tmp_path):
    binary = _executable(tmp_path / "whisper-cli")
    assert resolve_whisper_binary(str(binary)) == str(binary)


def test_falls_back_to_path(monkeypatch):
    monkeypatch.setattr("shutil.which", lambda n: "/usr/bin/whisper-cli")
    assert resolve_whisper_binary("") == "/usr/bin/whisper-cli"


def test_searches_known_build_locations(monkeypatch, tmp_path):
    monkeypatch.setattr("shutil.which", lambda n: None)
    built = tmp_path / "whispercpp" / "whisper.cpp" / "build" / "bin"
    built.mkdir(parents=True)
    binary = _executable(built / "whisper-cli")
    monkeypatch.setattr("pathlib.Path.home", lambda: tmp_path)
    assert resolve_whisper_binary("") == str(binary)


def test_raises_with_build_instructions_when_absent(monkeypatch, tmp_path):
    monkeypatch.setattr("shutil.which", lambda n: None)
    monkeypatch.setattr("pathlib.Path.home", lambda: tmp_path)
    with pytest.raises(FileNotFoundError, match="whisper.cpp"):
        resolve_whisper_binary("")


def test_configured_path_that_does_not_exist_is_ignored(monkeypatch, tmp_path):
    monkeypatch.setattr("shutil.which", lambda n: "/usr/bin/whisper-cli")
    assert resolve_whisper_binary("/nope/whisper-cli") == "/usr/bin/whisper-cli"


def test_model_url_is_derived_from_the_model_name():
    assert "ggml-medium.en.bin" in MODEL_URL.format(model="medium.en")


def _transcriber(tmp_path, calls, language="auto"):
    def runner(args):
        calls.append(args)
        out = args[args.index("--output-file") + 1]
        with open(f"{out}.txt", "w") as fh:
            fh.write("the transcript")
        return 0

    binary = _executable(tmp_path / "whisper-cli")
    model = tmp_path / "ggml-medium.en.bin"
    model.write_bytes(b"x")
    return WhisperCppTranscriber(
        binary=str(binary), model_path=str(model), language=language, runner=runner
    )


def test_transcribe_invokes_the_binary_with_the_model(tmp_path):
    calls = []
    audio = tmp_path / "a.wav"
    audio.write_bytes(b"x")
    assert _transcriber(tmp_path, calls).transcribe_file(audio) == "the transcript"
    assert str(tmp_path / "ggml-medium.en.bin") in calls[0]


def test_language_flag_omitted_when_auto(tmp_path):
    calls = []
    audio = tmp_path / "a.wav"
    audio.write_bytes(b"x")
    _transcriber(tmp_path, calls).transcribe_file(audio)
    assert "--language" not in calls[0]


def test_language_flag_sent_when_explicit(tmp_path):
    calls = []
    audio = tmp_path / "a.wav"
    audio.write_bytes(b"x")
    _transcriber(tmp_path, calls, language="hi").transcribe_file(audio)
    assert "--language" in calls[0]
    assert calls[0][calls[0].index("--language") + 1] == "hi"


def test_transcribe_raises_when_the_binary_fails(tmp_path):
    binary = _executable(tmp_path / "whisper-cli")
    model = tmp_path / "m.bin"
    model.write_bytes(b"x")
    audio = tmp_path / "a.wav"
    audio.write_bytes(b"x")
    t = WhisperCppTranscriber(
        binary=str(binary), model_path=str(model), runner=lambda a: 1
    )
    with pytest.raises(RuntimeError, match="whisper.cpp failed"):
        t.transcribe_file(audio)


def test_transcribe_raises_when_no_output_is_produced(tmp_path):
    binary = _executable(tmp_path / "whisper-cli")
    model = tmp_path / "m.bin"
    model.write_bytes(b"x")
    audio = tmp_path / "a.wav"
    audio.write_bytes(b"x")
    t = WhisperCppTranscriber(
        binary=str(binary), model_path=str(model), runner=lambda a: 0
    )
    with pytest.raises(RuntimeError, match="no transcript"):
        t.transcribe_file(audio)
