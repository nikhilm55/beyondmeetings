import re

from beyondmeetings.cli import build_parser, placeholder_name


def test_start_accepts_a_name():
    args = build_parser().parse_args(["start", "Client Kickoff"])
    assert args.command == "start"
    assert args.name == "Client Kickoff"


def test_start_name_is_optional():
    args = build_parser().parse_args(["start"])
    assert args.name is None


def test_placeholder_name_uses_the_clock():
    assert re.fullmatch(r"recording-\d{2}-\d{2}", placeholder_name())


def test_stop_takes_no_arguments():
    assert build_parser().parse_args(["stop"]).command == "stop"


def test_notes_accepts_a_transcript_path():
    args = build_parser().parse_args(["notes", "/tmp/t.txt"])
    assert args.command == "notes"
    assert args.transcript == "/tmp/t.txt"


def test_stop_without_a_recording_exits_cleanly(tmp_path, monkeypatch, capsys):
    """No traceback — this is the most likely first-run mistake."""
    import pytest

    from beyondmeetings import cli
    from beyondmeetings.config import Config

    monkeypatch.setattr(cli, "load_config", lambda: Config(data_dir=str(tmp_path)))
    with pytest.raises(SystemExit) as exc:
        cli.main(["stop"])
    assert "Nothing to stop" in str(exc.value)
